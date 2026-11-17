"""Choose the driver-based forecast's settings on the tuning window only.

Tries every combination of growth damping, monthly growth cap and pipeline included, and ranks
them by mean absolute percentage error on forecast origins Jul 2025 - Jan 2026. The winner is
then hard-coded in forecast_revenue.py and judged on the later test window, which this script
never looks at.
"""
import itertools
import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import forecast_revenue as F  # noqa: E402


def main():
    con = duckdb.connect(F.DB, read_only=True)
    rev, contracts, opps, hist, accts = F.load(con)
    total = F.company_total(rev)
    tuning = pd.date_range("2025-07-01", "2026-01-01", freq="MS")
    results = []
    for damping, cap_up, pipe in itertools.product(
            [0.8, 0.9, 1.0], [0.15, 0.25], [(), ("New Business",), ("New Business", "Expansion")]):
        errors = []
        for t in tuning:
            fc = F.forecast_driver(rev, contracts, opps, hist, accts, t, pipeline_types=pipe,
                                   damping=damping, growth_cap=(-0.30, cap_up))
            for m, g in fc.groupby("forecast_month"):
                if m <= F.ACTUALS_END:
                    errors.append(abs(g.forecast_usd.sum() - total[m]) / total[m])
        results.append({"damping": damping, "growth_cap": cap_up, "pipeline": "+".join(pipe) or "none",
                        "tuning_mape_pct": round(100 * float(np.mean(errors)), 2)})
    print(pd.DataFrame(results).sort_values("tuning_mape_pct").to_string(index=False))


if __name__ == "__main__":
    main()
