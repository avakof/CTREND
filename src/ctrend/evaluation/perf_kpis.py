"""Week-by-week performance and KPIs for a given period (M6 reporting).

Reports the three M6 variants side by side, because the difference between them IS
the result: `A` is the paper's frictionless construction, `B` restricts the short book
to coins with a live perpetual, and `C` is long-only inside the top half by dollar
volume. `C_net` applies the paper's most conservative cost scheme (50/60 bps) to the
long leg at the measured turnover.

Drawdown is computed on the compounded equity curve, not on cumulative sums — a
weekly series with 6-18% volatility is not well approximated additively.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

ANN = 52.0


def kpis(r: pd.Series, name: str, tc: float = 0.0) -> dict:
    r = r.dropna().astype(float)
    if tc:
        r = r - tc
    n = len(r)
    if n < 3:
        return {"variant": name, "weeks": n}
    eq = (1 + r).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    downside = r[r < 0]
    mu, sd = r.mean(), r.std(ddof=1)
    # longest stretch below a prior peak, in weeks
    under = (dd < -1e-12).astype(int)
    longest, cur = 0, 0
    for v in under:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    return {
        "variant": name,
        "weeks": n,
        "total_return_%": (eq.iloc[-1] - 1) * 100,
        "mean_wk_%": mu * 100,
        "median_wk_%": r.median() * 100,
        "vol_wk_%": sd * 100,
        "vol_ann_%": sd * np.sqrt(ANN) * 100,
        "sharpe_ann": mu / sd * np.sqrt(ANN) if sd > 0 else np.nan,
        "sortino_ann": (mu / downside.std(ddof=1) * np.sqrt(ANN)
                        if len(downside) > 1 and downside.std(ddof=1) > 0 else np.nan),
        "max_dd_%": dd.min() * 100,
        "calmar": (mu * ANN) / abs(dd.min()) if dd.min() < 0 else np.nan,
        "dd_weeks": longest,
        "hit_rate_%": (r > 0).mean() * 100,
        "best_wk_%": r.max() * 100,
        "worst_wk_%": r.min() * 100,
        "skew": r.skew(),
        "kurtosis": r.kurtosis(),
        "t_stat": mu / (sd / np.sqrt(n)) if sd > 0 else np.nan,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default="reports/m6_variants.csv")
    p.add_argument("--years", default="2025,2026")
    p.add_argument("--weekly-detail", action="store_true")
    a = p.parse_args(argv)

    d = pd.read_csv(a.src)
    d["year"] = d["week"] // 100
    years = [int(y) for y in a.years.split(",")]

    # Cost per week for the long-only variant at the 50/60 bps scheme. Turnover is
    # one-sided here (long book only), taken from the measured H-L turnover in the
    # gate; applied as a flat drag so the figure is conservative, not optimistic.
    TC_LONG = 0.0050 * 0.70

    for y in years:
        s = d[d.year == y]
        if s.empty:
            continue
        print("\n" + "=" * 78)
        print(f"{y}  —  {len(s)} weeks   [{int(s.week.min())} – {int(s.week.max())}]")
        print("=" * 78)
        rows = [
            kpis(s["A_hl"], "A  paper-faithful H−L (frictionless)"),
            kpis(s["B_hl"], "B  feasibility-masked short"),
            kpis(s["C_long"], "C  long-only, top-half liquidity"),
            kpis(s["C_long"], "C_net  long-only net of 50/60bps", tc=TC_LONG),
        ]
        t = pd.DataFrame(rows).set_index("variant")
        order = ["weeks", "total_return_%", "mean_wk_%", "vol_ann_%", "sharpe_ann",
                 "sortino_ann", "max_dd_%", "dd_weeks", "calmar", "hit_rate_%",
                 "best_wk_%", "worst_wk_%", "skew", "t_stat"]
        print(t[order].T.to_string(float_format=lambda v: f"{v:9.2f}"))

    if a.weekly_detail:
        for y in years:
            s = d[d.year == y].copy()
            if s.empty:
                continue
            # NOT "eq": DataFrame.eq is a method, so attribute access silently
            # returns the bound method instead of the column.
            s["equity"] = (1 + s["A_hl"]).cumprod()
            s["dd_%"] = (s["equity"] / s["equity"].cummax() - 1) * 100
            print(f"\n--- {y} week by week (%, A = frictionless H−L) ---")
            print(f"{'week':>7}{'A_hl':>8}{'B_hl':>8}{'C_long':>8}{'mkt':>8}"
                  f"{'long_leg':>9}{'short_leg':>10}{'cum_A':>8}{'DD_A':>8}{'n':>6}")
            for _, r in s.iterrows():
                def f(v):
                    return f"{v * 100:8.2f}" if pd.notna(v) else "     n/a"
                print(f"{int(r.week):>7}{f(r.A_hl)}{f(r.B_hl)}{f(r.C_long)}{f(r.mkt)}"
                      f"{f(r.long_leg)}{f(r.short_leg)}"
                      f"{(r['equity'] - 1) * 100:8.1f}{r['dd_%']:8.1f}{int(r['n']):6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
