"""Short-only book derived from CTREND — week-by-week performance (M6 reporting).

Four ways of holding "the short side", because they answer different questions and
differ enormously:

    S1  outright short, all names      -q1                 short the bottom quintile
    S2  outright short, FEASIBLE only  -q1_shortable       restricted to coins with a
                                                           live Binance perpetual
    S3  market-neutral, all names      mkt - q1            short q1 / long the market
    S4  market-neutral, FEASIBLE only  mkt - q1_shortable

S1/S2 are what a desk running a short book actually earns. S3/S4 are the "short leg
contribution" quoted in the decay report, which is a *relative* figure and flatters
the short side whenever the market falls.

`q1_shortable` is recovered as `q5 - B_hl`, since `B_hl = q5 - vw(q1 ∩ shortable)`.

**Costs.** Transaction cost is applied at the paper's short-leg rates (40/50/60 bps)
against measured turnover. Perpetual **funding is deliberately NOT credited**: over
this period funding was on average positive (longs pay shorts), so a short book would
historically have *earned* it. Crediting an average tailwind to a strategy whose
viability is in question would flatter it, so it is left out and flagged instead.

**What is still not modelled** — and all of it cuts against a short book: borrow
recall and forced buy-ins, market impact in the bottom quintile (small, illiquid
coins by construction), position limits per venue, and the unbounded left tail of a
short. These figures are therefore an upper bound on what was achievable.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

ANN = 52.0
TC_SHORT = {"40bps": 0.0040, "50bps": 0.0050, "60bps": 0.0060}


def kpis(r: pd.Series, name: str) -> dict:
    r = r.dropna().astype(float)
    n = len(r)
    if n < 3:
        return {"book": name, "weeks": n}
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1.0
    down = r[r < 0]
    mu, sd = r.mean(), r.std(ddof=1)
    under = (dd < -1e-12).astype(int)
    longest = cur = 0
    for v in under:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    return {
        "book": name, "weeks": n,
        "total_%": (eq.iloc[-1] - 1) * 100,
        "mean_wk_%": mu * 100,
        "vol_ann_%": sd * np.sqrt(ANN) * 100,
        "sharpe": mu / sd * np.sqrt(ANN) if sd > 0 else np.nan,
        "sortino": (mu / down.std(ddof=1) * np.sqrt(ANN)
                    if len(down) > 1 and down.std(ddof=1) > 0 else np.nan),
        "max_dd_%": dd.min() * 100,
        "dd_weeks": longest,
        "hit_%": (r > 0).mean() * 100,
        "best_%": r.max() * 100,
        "worst_%": r.min() * 100,
        "skew": r.skew(),
        "t_stat": mu / (sd / np.sqrt(n)) if sd > 0 else np.nan,
    }


def build(src: str, y0: int, y1: int) -> pd.DataFrame:
    d = pd.read_csv(src)
    d["year"] = d["week"] // 100
    d = d[(d.year >= y0) & (d.year <= y1)].copy()
    d["q1_feas"] = d["q5"] - d["B_hl"]          # see module docstring
    d["S1"] = -d["q1"]
    d["S2"] = -d["q1_feas"]
    d["S3"] = d["mkt"] - d["q1"]
    d["S4"] = d["mkt"] - d["q1_feas"]
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default="reports/m6_variants.csv")
    p.add_argument("--from-year", type=int, default=2024)
    p.add_argument("--to-year", type=int, default=2026)
    p.add_argument("--turnover", type=float, default=0.70,
                   help="weekly one-sided turnover of the short book")
    p.add_argument("--detail", action="store_true")
    a = p.parse_args(argv)

    d = build(a.src, a.from_year, a.to_year)
    print(f"\nShort-only books, {a.from_year}–{a.to_year}: {len(d)} weeks "
          f"[{int(d.week.min())} – {int(d.week.max())}]")
    print(f"names in the bottom quintile with a live perpetual: "
          f"{d.short_frac.mean() * 100:.1f}% on average")

    books = [("S1  outright short, all names", d["S1"]),
             ("S2  outright short, FEASIBLE only", d["S2"]),
             ("S3  market-neutral, all names", d["S3"]),
             ("S4  market-neutral, FEASIBLE only", d["S4"])]
    t = pd.DataFrame([kpis(s, n) for n, s in books]).set_index("book")
    cols = ["weeks", "total_%", "mean_wk_%", "vol_ann_%", "sharpe", "sortino",
            "max_dd_%", "dd_weeks", "hit_%", "best_%", "worst_%", "skew", "t_stat"]
    print("\n=== GROSS ===")
    print(t[cols].T.to_string(float_format=lambda v: f"{v:9.2f}"))

    print(f"\n=== NET of short-leg transaction costs (turnover {a.turnover:.0%}/wk) ===")
    rows = []
    for label, bps in TC_SHORT.items():
        for n, s in (("S2  outright, feasible", d["S2"]), ("S4  mkt-neutral, feasible", d["S4"])):
            k = kpis(s - bps * a.turnover, f"{n} @ {label}")
            rows.append(k)
    print(pd.DataFrame(rows).set_index("book")[
        ["total_%", "mean_wk_%", "sharpe", "max_dd_%", "t_stat"]
    ].to_string(float_format=lambda v: f"{v:9.2f}"))

    print("\n=== by calendar year (S2 outright feasible, gross) ===")
    for y, s in d.groupby("year"):
        k = kpis(s["S2"], str(y))
        if "total_%" in k:
            print(f"  {y}  weeks={k['weeks']:>3}  total={k['total_%']:>8.1f}%  "
                  f"mean={k['mean_wk_%']:>6.2f}%  sharpe={k['sharpe']:>6.2f}  "
                  f"maxDD={k['max_dd_%']:>7.1f}%")

    if a.detail:
        print(f"\n--- week by week (%), {a.from_year}–{a.to_year} ---")
        e1 = (1 + d["S1"]).cumprod()
        e2 = (1 + d["S2"]).cumprod()
        d = d.assign(cum1=(e1 - 1) * 100, cum2=(e2 - 1) * 100,
                     dd2=(e2 / e2.cummax() - 1) * 100)
        print(f"{'week':>7}{'S1':>8}{'S2':>8}{'S3':>8}{'S4':>8}{'mkt':>8}"
              f"{'cumS1':>9}{'cumS2':>9}{'ddS2':>8}{'feas%':>7}{'n':>6}")
        for _, r in d.iterrows():
            def f(v):
                return f"{v * 100:8.2f}" if pd.notna(v) else "     n/a"
            print(f"{int(r['week']):>7}{f(r['S1'])}{f(r['S2'])}{f(r['S3'])}{f(r['S4'])}"
                  f"{f(r['mkt'])}{r['cum1']:9.1f}{r['cum2']:9.1f}{r['dd2']:8.1f}"
                  f"{r['short_frac'] * 100:7.1f}{int(r['n']):6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
