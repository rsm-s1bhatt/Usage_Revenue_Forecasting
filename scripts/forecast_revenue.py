"""Forecast monthly revenue for a usage-based business, and backtest it.

Revenue here is consumption-based: each month a customer pays the greater of their committed
minimum and their discounted usage. The driver-based forecast follows that mechanic:

  account revenue = max(commit in force, forecast usage)      for every live account
                  x survival (segment churn rate, learned from history)
                  + expected revenue from open new-business deals (calibrated stage win rates, ramp)

Open expansion deals add their monthly value from the month they are expected to close.

Settings (damping, growth cap, which pipeline to include) were chosen on a tuning window of
forecast origins Jul 2025 - Jan 2026. Results are reported on a later, untouched test window
(origins Apr - Oct 2026), so the reported error is not the error the settings were tuned on.

It is compared against two baselines on a rolling-origin backtest (every forecast uses only
data available at its origin date):
  naive  - next months equal last month
  trend  - company-level log-linear trend over the last 6 months

Outputs, written back to the warehouse (schema `ml`) and to docs/:
  ml.revenue_forecast     account-level forecast for the 3 months after the end of actuals
  ml.forecast_backtest    every backtest forecast with its actual and error
  docs/forecast_backtest.png
"""
from __future__ import annotations

import os
import sys

import duckdb
import numpy as np
import pandas as pd

DB = os.path.join(os.path.dirname(__file__), "..", "target", "usage_revenue.duckdb")
DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")
ACTUALS_END = pd.Timestamp("2026-10-31")
HORIZON = 3
DAMPING = 1.0              # 1.0 = no fading; chosen on the tuning window by scripts/tune_forecast.py
GROWTH_CAP = (-0.30, 0.15) # monthly growth bounds for a single account's usage trend
RAMP = [0.3, 0.55, 0.8, 1.0]  # share of contract value a new logo bills in its first months


def load(con):
    rev = con.sql("""
        select account_id, revenue_month, segment, revenue_usd, usage_net_usd
        from fct_revenue_monthly""").df()
    contracts = con.sql("select * from stg_billing__contracts").df()
    opps = con.sql("""
        select opportunity_id, account_id, opportunity_type, amount_usd, created_date, close_date, is_won, is_closed
        from stg_crm__opportunities where is_valid""").df()
    hist = con.sql("select * from stg_crm__opportunity_history").df()
    accts = con.sql("select account_id, segment from stg_crm__accounts").df()
    for df, cols in [(rev, ["revenue_month"]), (contracts, ["start_date", "end_date"]),
                     (opps, ["created_date", "close_date"]), (hist, ["entered_date"])]:
        for c in cols:
            df[c] = pd.to_datetime(df[c])
    return rev, contracts, opps, hist, accts


def months_after(t, n):
    return [t + pd.DateOffset(months=k) for k in range(n)]


def stage_win_rates(opps, hist, t):
    """Win rate by the furthest stage reached, from opportunities closed before t."""
    closed = opps[opps.is_closed & (opps.close_date < t)]
    h = hist[hist.opportunity_id.isin(closed.opportunity_id) & ~hist.stage.str.startswith("Closed")]
    h = h.merge(closed[["opportunity_id", "is_won"]], on="opportunity_id")
    return h.groupby("stage").is_won.mean().to_dict()


def open_pipeline(opps, hist, t):
    """Opportunities open at t, with the stage they were in at t (point in time)."""
    o = opps[(opps.created_date < t) & ((opps.close_date >= t) | ~opps.is_closed)]
    h = hist[(hist.entered_date < t) & ~hist.stage.str.startswith("Closed")]
    stage_at_t = h.sort_values("entered_date").groupby("opportunity_id").stage.last()
    o = o.merge(stage_at_t.rename("stage_at_t"), left_on="opportunity_id", right_index=True)
    return o


def segment_monthly_churn(rev, t):
    """Share of account-months before t that were the account's last billing month (excluding the latest)."""
    r = rev[rev.revenue_month < t - pd.DateOffset(months=1)]
    last = rev[rev.revenue_month < t].groupby("account_id").revenue_month.max()
    r = r.merge(last.rename("last_month"), left_on="account_id", right_index=True)
    r["churned_here"] = r.revenue_month == r.last_month
    return r.groupby("segment").churned_here.mean().to_dict()


def forecast_driver(rev, contracts, opps, hist, accts, t, pipeline_types=("New Business", "Expansion"),
                    damping=DAMPING, growth_cap=GROWTH_CAP):
    """Account-level forecast for the HORIZON months starting at t, using only data before t."""
    hist_rev = rev[rev.revenue_month < t]
    live = hist_rev[hist_rev.revenue_month == t - pd.DateOffset(months=1)].account_id.unique()
    churn = segment_monthly_churn(rev, t)
    rows = []
    signed = contracts[contracts.start_date < t]
    for acct in live:
        a = hist_rev[hist_rev.account_id == acct].sort_values("revenue_month")
        seg = a.segment.iloc[-1]
        u = a.usage_net_usd.clip(lower=1).values[-4:]
        if len(u) >= 3:
            slope = np.polyfit(np.arange(len(u)), np.log(u), 1)[0]
        else:
            slope = 0.0
        g = float(np.clip(slope, *growth_cap))
        base = float(np.mean(u[-2:])) if len(u) >= 2 else float(u[-1])
        cum = 0.0
        surv = 1.0
        for h, m in enumerate(months_after(t, HORIZON), start=1):
            cum += g * damping ** h
            usage_hat = base * np.exp(cum)
            c = signed[(signed.account_id == acct) & (signed.start_date <= m) & (signed.end_date >= m)]
            commit = float(c.monthly_commit_usd.max()) if len(c) else 0.0
            surv *= 1 - churn.get(seg, 0.0)
            rows.append((acct, m, h, "existing", max(commit, usage_hat) * surv, commit))
    if pipeline_types:
        wr = stage_win_rates(opps, hist, t)
        pipe = open_pipeline(opps, hist, t)
        pipe = pipe[pipe.opportunity_type.isin(pipeline_types)]
        for _, o in pipe.iterrows():
            p = wr.get(o.stage_at_t, 0.0)
            close_m = o.close_date.to_period("M").to_timestamp()
            comp = "new_logo_pipeline" if o.opportunity_type == "New Business" else "expansion_pipeline"
            for h, m in enumerate(months_after(t, HORIZON), start=1):
                if m >= close_m:
                    k = (m.year - close_m.year) * 12 + m.month - close_m.month
                    ramp = RAMP[min(k, 3)] if comp == "new_logo_pipeline" else 1.0
                    rows.append((o.account_id, m, h, comp, o.amount_usd / 12 * p * ramp, 0.0))
    return pd.DataFrame(rows, columns=["account_id", "forecast_month", "horizon", "component", "forecast_usd", "commit_usd"])


def company_total(rev):
    return rev.groupby("revenue_month").revenue_usd.sum()


def baseline_forecasts(total, t):
    past = total[total.index < t]
    out = {}
    last = past.iloc[-1]
    y = np.log(past.iloc[-6:].values)
    slope, icpt = np.polyfit(np.arange(len(y)), y, 1)
    for h, m in enumerate(months_after(t, HORIZON), start=1):
        out[("naive", m)] = last
        out[("trend", m)] = float(np.exp(icpt + slope * (len(y) - 1 + h)))
    return out


def main():
    con = duckdb.connect(DB)
    rev, contracts, opps, hist, accts = load(con)
    total = company_total(rev)

    windows = {"tuning": pd.date_range("2025-07-01", "2026-01-01", freq="MS"),
               "test": pd.date_range("2026-04-01", "2026-10-01", freq="MS")}
    bt = []
    for window, origins in windows.items():
        for t in origins:
            fc = forecast_driver(rev, contracts, opps, hist, accts, t)
            fc_existing = fc[fc.component == "existing"]
            base = baseline_forecasts(total, t)
            for h, m in enumerate(months_after(t, HORIZON), start=1):
                if m > ACTUALS_END:
                    continue
                actual = float(total.get(m, np.nan))
                preds = {
                    "naive": base[("naive", m)],
                    "trend": base[("trend", m)],
                    "driver_existing_only": fc_existing[fc_existing.forecast_month == m].forecast_usd.sum(),
                    "driver_with_pipeline": fc[fc.forecast_month == m].forecast_usd.sum(),
                }
                for method, p in preds.items():
                    bt.append((window, t, m, h, method, p, actual))
    bt = pd.DataFrame(bt, columns=["window", "origin_month", "forecast_month", "horizon", "method", "forecast_usd", "actual_usd"])
    bt["abs_pct_error"] = (bt.forecast_usd - bt.actual_usd).abs() / bt.actual_usd

    for window in windows:
        w = bt[bt.window == window]
        summary = w.pivot_table(index="method", columns="horizon", values="abs_pct_error", aggfunc="mean") * 100
        summary["all"] = w.groupby("method").abs_pct_error.mean() * 100
        summary["n_forecasts"] = w.groupby("method").size()
        print(f"\nMAPE (%) by method and months ahead, {window} window:")
        print(summary.round(2).to_string())

    # final forecast from the end of actuals, with the method chosen on the backtest
    t_final = ACTUALS_END + pd.Timedelta(days=1)
    final = forecast_driver(rev, contracts, opps, hist, accts, t_final)
    final["forecast_month"] = final.forecast_month.dt.date
    bt["origin_month"] = bt.origin_month.dt.date
    bt["forecast_month"] = bt.forecast_month.dt.date

    con.sql("create schema if not exists ml")
    con.register("final_df", final)
    con.register("bt_df", bt)
    con.sql("create or replace table ml.revenue_forecast as select * from final_df")
    con.sql("create or replace table ml.forecast_backtest as select * from bt_df")
    print("\nForecast by month (driver_with_pipeline):")
    print(final.groupby("forecast_month").forecast_usd.sum().round(0).to_string())

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        os.makedirs(DOCS, exist_ok=True)
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(total.index, total.values / 1e6, color="#222", lw=2, label="Actual")
        one = bt[(bt.horizon == 1)]
        for method, col in [("naive", "#999"), ("trend", "#d08c2b"), ("driver_with_pipeline", "#1f6fb2")]:
            s = one[one.method == method]
            ax.plot(pd.to_datetime(s.forecast_month), s.forecast_usd / 1e6, "o--", color=col, ms=4, label=f"{method}, 1 month ahead")
        fm = final.groupby("forecast_month").forecast_usd.sum()
        ax.plot(pd.to_datetime(fm.index), fm.values / 1e6, "s-", color="#1f6fb2", alpha=0.5, label="Forecast Nov 2026 - Jan 2027")
        ax.set_ylabel("Monthly revenue ($M, synthetic)")
        ax.set_xlim(pd.Timestamp("2025-06-01"), pd.Timestamp("2027-02-01"))
        ax.legend(fontsize=8, frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(os.path.join(DOCS, "forecast_backtest.png"), dpi=150)
    except ImportError:
        print("matplotlib not installed; skipping chart", file=sys.stderr)


if __name__ == "__main__":
    main()
