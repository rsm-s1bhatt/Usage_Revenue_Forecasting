"""Generate a synthetic GTM dataset for a usage-based AI inference platform.

Every table is synthetic and seeded, so each run produces identical files. Real customer, billing
and telemetry data is private; this generator creates data with the same shape and the same
business mechanics (commits, consumption above commit, GPU mix, ramps, expansions and churn).

Outputs (data/raw/):
  crm_accounts.csv           one row per account, with segment, region and owner
  crm_reps.csv               sales reps with region and annual quota
  crm_opportunities.csv      Salesforce-style opportunities (new, expansion, renewal)
  crm_opportunity_history.csv  stage changes per opportunity, for point-in-time pipeline
  billing_contracts.csv      annual commit contracts with discounts
  billing_invoices.csv       monthly invoices: max(commit, discounted usage)
  telemetry_usage_daily.csv  daily GPU hours and requests per account and GPU type
  telemetry_deployments.csv  model deployment events per account
  ref_gpu_rates.csv          illustrative list price and infrastructure cost per GPU hour
  plan_revenue_monthly.csv   2026 revenue plan by region, set at the start of the year

Planted data problems (the data-quality models must find exactly these):
  4 duplicate opportunities, 3 opportunities with an unknown account,
  5 invoices that do not reconcile to usage, 3 usage rows with negative GPU hours.
"""
from __future__ import annotations

import csv
import os
from datetime import date, timedelta

import numpy as np

SEED = 42
START = date(2024, 1, 1)
END = date(2026, 10, 31)          # last day of actuals
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

REGIONS = ["NA-West", "NA-East", "EMEA", "APAC"]
REGION_P = [0.38, 0.30, 0.20, 0.12]
SEGMENTS = {
    #           share, base GPU h/day, monthly growth mean, has commit, discount range
    "Enterprise": (0.15, 260.0, 0.020, 1.00, (0.15, 0.30)),
    "Mid-Market": (0.35, 55.0, 0.025, 0.80, (0.05, 0.15)),
    "Startup":    (0.50, 12.0, 0.035, 0.25, (0.00, 0.05)),
}
INDUSTRIES = ["AI-native apps", "Developer tools", "Healthcare AI", "Enterprise SaaS", "Media & content"]
# Illustrative $/GPU-hour. Not Baseten's or any vendor's real prices.
GPU_RATES = {"L4": (0.85, 0.40), "A100": (3.20, 1.75), "H100": (5.50, 3.30), "B200": (8.75, 6.10)}
B200_LAUNCH = date(2025, 7, 1)
STAGES = [("Discovery", 0.10), ("Evaluation", 0.25), ("Technical Validation", 0.50),
          ("Negotiation", 0.75)]


def month_starts(a: date, b: date):
    d = date(a.year, a.month, 1)
    while d <= b:
        yield d
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def days_in_month(d: date) -> int:
    return (add_months(d, 1) - d).days


def write(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)
    months = list(month_starts(START, END))
    n_months = len(months)

    # ---- reps -------------------------------------------------------------------------
    reps = []
    for i, region in enumerate(REGIONS):
        for j in range({"NA-West": 6, "NA-East": 5, "EMEA": 4, "APAC": 3}[region]):
            reps.append((f"REP{len(reps)+1:03d}", region, int(rng.choice([900_000, 1_200_000, 1_500_000]))))
    write("crm_reps.csv", ["rep_id", "region", "annual_quota_usd"], reps)

    # ---- accounts and their latent usage paths ---------------------------------------
    n_accounts = 320
    seg_names = list(SEGMENTS)
    seg_p = [SEGMENTS[s][0] for s in seg_names]
    accounts, contracts, opps, opp_hist, deployments = [], [], [], [], []
    usage_rows, monthly_usage_value = [], {}   # (acct, month) -> usage value at list price
    opp_n = 0

    def new_opp(acct, rep, typ, amount, created, close, won):
        nonlocal opp_n
        opp_n += 1
        oid = f"OPP{opp_n:05d}"
        # stage history: walk the open stages between created and close
        # won deals usually reach late stages; lost deals usually drop out early
        if close <= END and not won:
            n_st = int(rng.choice([1, 2, 3, 4], p=[0.40, 0.30, 0.20, 0.10]))
        elif close <= END:
            n_st = int(rng.choice([2, 3, 4], p=[0.15, 0.40, 0.45]))
        else:
            n_st = int(rng.integers(1, 5))
        span = max((close - created).days, n_st)
        cuts = sorted(rng.choice(np.arange(1, span), size=n_st - 1, replace=False)) if span > n_st else list(range(1, n_st))
        dates = [created] + [created + timedelta(days=int(c)) for c in cuts]
        for (st, _), d in zip(STAGES[:n_st], dates):
            opp_hist.append((oid, st, d.isoformat()))
        final = None
        if close <= END:
            final = "Closed Won" if won else "Closed Lost"
            opp_hist.append((oid, final, close.isoformat()))
        stage = final or STAGES[n_st - 1][0]
        opps.append([oid, acct, rep, typ, stage, round(amount, 2), created.isoformat(), close.isoformat()])
        return oid

    # accounts arrive faster over time (the business is growing)
    arrival_w = np.linspace(1.0, 3.0, n_months)
    arrival_w /= arrival_w.sum()
    for a in range(n_accounts):
        acct = f"ACC{a+1:04d}"
        seg = rng.choice(seg_names, p=seg_p)
        _, base, g_mean, p_commit, disc_rng = SEGMENTS[seg]
        region = rng.choice(REGIONS, p=REGION_P)
        region_reps = [r for r in reps if r[1] == region]
        rep = region_reps[int(rng.integers(len(region_reps)))][0]
        start_m = int(rng.choice(n_months, p=arrival_w))
        start = months[start_m] + timedelta(days=int(rng.integers(0, 20)))
        accounts.append([acct, f"Customer {a+1:04d}", seg, rng.choice(INDUSTRIES), region, rep, start.isoformat()])

        primary = rng.choice(["L4", "A100", "H100"], p=[0.30, 0.35, 0.35])
        level = base * rng.lognormal(0, 0.6)
        growth = rng.normal(g_mean, 0.03)
        discount = float(rng.uniform(*disc_rng))
        has_commit = rng.random() < p_commit

        # latent monthly multipliers: ramp, growth, expansion steps, churn decline
        mult = np.zeros(n_months)
        gpu_mix = {}                 # month -> {gpu: share}
        churn_m, expansions = None, []
        for m in range(start_m, n_months):
            age = m - start_m
            ramp = min(1.0, 0.3 + 0.25 * age)
            mult[m] = ramp * (1 + growth) ** age
        # expansion events: a new workload goes live, signalled 1-2 months earlier by deployments
        lam = 0.045 if seg != "Startup" else 0.035
        for m in range(start_m + 3, n_months):
            if rng.random() < lam:
                expansions.append(m)
                mult[m:] *= rng.uniform(1.4, 2.0)
        # churn: hazard per month; usage declines for 2-3 months first
        hz = {"Enterprise": 0.010, "Mid-Market": 0.018, "Startup": 0.030}[seg]
        for m in range(start_m + 4, n_months):
            if rng.random() < hz:
                churn_m = m
                fade = int(rng.integers(1, 3))
                for k in range(fade):
                    mm = m - fade + k
                    if mm > start_m:
                        mult[mm] *= (1 - (k + 1) / (fade + 1))
                mult[m:] = 0
                break

        # temporary dips (holidays, a paused workload) that recover, so a dip alone is not churn
        for m in range(start_m + 3, n_months):
            if mult[m] > 0 and rng.random() < 0.05:
                mult[m] *= rng.uniform(0.35, 0.7)

        # GPU mix: primary type, plus some move work to B200 after launch, plus a second type after expansions
        second = None
        for m in range(start_m, n_months):
            mix = {primary: 1.0}
            if second:
                mix = {primary: 0.65, second: 0.35}
            if m in expansions:
                second = rng.choice([g for g in ["L4", "A100", "H100", "B200"] if g != primary and (g != "B200" or months[m] >= B200_LAUNCH)])
                mix = {primary: 0.65, second: 0.35}
            gpu_mix[m] = mix

        # deployments: steady cadence, a burst 1-2 months before each expansion, a drop before churn
        for m in range(start_m, n_months):
            if mult[m] == 0 and m > start_m:
                break
            rate = 1.0 + 0.4 * np.log1p(level / 20)
            if any(0 < e - m <= 2 for e in expansions):
                rate *= 2.0
            if churn_m is not None and 0 < churn_m - m <= 2:
                rate *= 0.5
            if rng.random() < 0.08:          # bursts and lulls that lead nowhere, as in real data
                rate *= float(rng.choice([0.3, 2.0]))
            for _ in range(rng.poisson(rate)):
                d = months[m] + timedelta(days=int(rng.integers(0, days_in_month(months[m]))))
                if start <= d <= END:
                    deployments.append([acct, d.isoformat(), f"model-{int(rng.integers(1, 40))}"])

        # daily usage
        for m in range(start_m, n_months):
            if mult[m] == 0:
                continue
            ms = months[m]
            active_p = 0.97 if (churn_m is None or churn_m - m > 2) else 0.85
            for k in range(days_in_month(ms)):
                d = ms + timedelta(days=k)
                if d < start or d > END or rng.random() > active_p:
                    continue
                wk = 0.85 if d.weekday() >= 5 else 1.05
                hours = level * mult[m] * wk * rng.lognormal(0, 0.18)
                for gpu, share in gpu_mix[m].items():
                    h = round(hours * share, 2)
                    if h <= 0.01:
                        continue
                    req = int(h * rng.uniform(900, 1400))
                    usage_rows.append([d.isoformat(), acct, gpu, h, req])
                    key = (acct, ms)
                    monthly_usage_value[key] = monthly_usage_value.get(key, 0.0) + h * GPU_RATES[gpu][0]

        # contracts: annual commits sized at 70-90% of expected usage at signing, renewed yearly
        first_val = level * 0.55 * 30 * GPU_RATES[primary][0] * (1 - discount)
        new_opp(acct, rep, "New Business", first_val * 12, start - timedelta(days=int(rng.integers(30, 120))), start, True)
        if has_commit:
            c_start = months[start_m]
            k = 0
            while c_start <= END and (churn_m is None or months[churn_m] > c_start):
                prior = [monthly_usage_value.get((acct, add_months(c_start, -i)), 0) for i in range(1, 4)]
                ref = np.mean([p for p in prior if p > 0]) * (1 - discount) if any(prior) else first_val
                commit = round(ref * rng.uniform(0.70, 0.90), -2)
                c_end = add_months(c_start, 12) - timedelta(days=1)
                contracts.append([f"CTR{len(contracts)+1:05d}", acct, c_start.isoformat(), c_end.isoformat(), commit, round(discount, 4)])
                if k > 0:
                    new_opp(acct, rep, "Renewal", commit * 12, c_start - timedelta(days=int(rng.integers(45, 90))), c_start, True)
                c_start = add_months(c_start, 12)
                k += 1
        for e in expansions:
            amt = (monthly_usage_value.get((acct, months[e]), 0) - monthly_usage_value.get((acct, months[e - 1]), 0)) * 12 * (1 - discount)
            close = months[e]
            new_opp(acct, rep, "Expansion", max(amt, 5000), close - timedelta(days=int(rng.integers(30, 75))), close, True)
        # open pipeline at the end of actuals: some expansions in flight
        if churn_m is None and rng.random() < 0.18:
            close = END + timedelta(days=int(rng.integers(15, 150)))
            amt = monthly_usage_value.get((acct, months[-1]), 1000) * rng.uniform(4, 10)
            new_opp(acct, rep, "Expansion", amt, END - timedelta(days=int(rng.integers(10, 90))), close, True)
        # some lost deals along the way
        if rng.random() < 0.55:
            cl = start + timedelta(days=int(rng.integers(60, 400)))
            if cl <= END:
                new_opp(acct, rep, "Expansion", float(rng.uniform(20_000, 300_000)), cl - timedelta(days=60), cl, False)

    # prospects: new-logo pipeline with no usage yet (open, plus historical losses)
    for p in range(160):
        acct = f"ACC{n_accounts+p+1:04d}"
        seg = rng.choice(seg_names, p=seg_p)
        region = rng.choice(REGIONS, p=REGION_P)
        region_reps = [r for r in reps if r[1] == region]
        rep = region_reps[int(rng.integers(len(region_reps)))][0]
        accounts.append([acct, f"Prospect {p+1:04d}", seg, rng.choice(INDUSTRIES), region, rep, ""])
        amt = SEGMENTS[seg][1] * 0.5 * 30 * 3.0 * 12 * rng.lognormal(0, 0.5)
        if rng.random() < 0.30:
            close = END + timedelta(days=int(rng.integers(10, 180)))
            new_opp(acct, rep, "New Business", amt, END - timedelta(days=int(rng.integers(20, 150))), close, True)
        else:
            close = START + timedelta(days=int(rng.integers(90, (END - START).days)))
            new_opp(acct, rep, "New Business", amt, close - timedelta(days=int(rng.integers(40, 120))), close, False)

    # ---- invoices ---------------------------------------------------------------------
    invoices = []
    ctr_by_acct = {}
    for c in contracts:
        ctr_by_acct.setdefault(c[1], []).append(c)
    disc_by_acct = {c[1]: c[5] for c in contracts}
    acct_seg = {a[0]: a[2] for a in accounts}
    for (acct, ms), val in sorted(monthly_usage_value.items()):
        if ms > END:
            continue
        commit, disc = 0.0, disc_by_acct.get(acct, 0.0)
        for c in ctr_by_acct.get(acct, []):
            if date.fromisoformat(c[2]) <= ms <= date.fromisoformat(c[3]):
                commit, disc = c[4], c[5]
        usage_net = val * (1 - disc)
        billed = max(commit, usage_net)
        invoices.append([f"INV-{acct}-{ms:%Y%m}", acct, ms.isoformat(), round(commit, 2), round(usage_net, 2), round(billed, 2)])

    # ---- plan: 2026 revenue plan by region, set from Q4 2025 run-rate plus 8% planned monthly growth --
    plan = []
    q4 = {r: 0.0 for r in REGIONS}
    acct_region = {a[0]: a[4] for a in accounts}
    for inv in invoices:
        if inv[2] in ("2025-10-01", "2025-11-01", "2025-12-01"):
            q4[acct_region[inv[1]]] += inv[5] / 3
    for r in REGIONS:
        for i, ms in enumerate(month_starts(date(2026, 1, 1), date(2026, 12, 1))):
            plan.append([r, ms.isoformat(), round(q4[r] * (1.08 ** (i + 1)), 2)])

    # ---- planted data problems --------------------------------------------------------
    for o in rng.choice(len(opps), size=4, replace=False):              # duplicates
        dup = list(opps[o])
        dup[0] = f"OPP{opp_n + 1:05d}"
        opp_n += 1
        opps.append(dup)
    for k in range(3):                                                    # unknown account
        o = list(opps[int(rng.integers(len(opps)))])
        o[0] = f"OPP{opp_n + 1:05d}"
        opp_n += 1
        o[1] = f"ACC9{k+1:03d}"
        opps.append(o)
    for i in rng.choice(len(invoices), size=5, replace=False):           # billing mismatches
        invoices[i][5] = round(invoices[i][5] * float(rng.choice([0.92, 0.95, 1.06, 1.09])), 2)
    for i in rng.choice(len(usage_rows), size=3, replace=False):         # negative usage
        usage_rows[i][3] = -abs(usage_rows[i][3])

    write("crm_accounts.csv", ["account_id", "account_name", "segment", "industry", "region", "owner_rep_id", "first_usage_date"], accounts)
    write("crm_opportunities.csv", ["opportunity_id", "account_id", "owner_rep_id", "opportunity_type", "stage", "amount_usd", "created_date", "close_date"], opps)
    write("crm_opportunity_history.csv", ["opportunity_id", "stage", "entered_date"], opp_hist)
    write("billing_contracts.csv", ["contract_id", "account_id", "start_date", "end_date", "monthly_commit_usd", "discount_pct"], contracts)
    write("billing_invoices.csv", ["invoice_id", "account_id", "invoice_month", "commit_usd", "usage_net_usd", "billed_usd"], invoices)
    write("telemetry_usage_daily.csv", ["usage_date", "account_id", "gpu_type", "gpu_hours", "requests"], usage_rows)
    write("telemetry_deployments.csv", ["account_id", "deployed_date", "model_name"], deployments)
    write("ref_gpu_rates.csv", ["gpu_type", "list_price_per_gpu_hour", "infra_cost_per_gpu_hour"], [[g, p, c] for g, (p, c) in GPU_RATES.items()])
    write("plan_revenue_monthly.csv", ["region", "plan_month", "plan_revenue_usd"], plan)
    print(f"accounts {len(accounts)}, opportunities {len(opps)}, contracts {len(contracts)}, "
          f"invoices {len(invoices)}, usage rows {len(usage_rows)}, deployments {len(deployments)}")


if __name__ == "__main__":
    main()
