"""Long-only book derived from CTREND — week-by-week performance (M6 reporting).

Four constructions plus the benchmark that actually matters:

    L1  outright long, all names        q5                top CTREND quintile
    L2  outright long, LIQUID only      C_long            top quintile within the
                                                          top half by dollar volume
    L3  market-neutral, all names       q5 - mkt          the "long leg" figure
    L4  market-neutral, LIQUID only     C_long - C_mkt
    BM  buy-and-hold the market         mkt               value-weighted universe

**For a long-only book the benchmark is not zero, it is the market.** A long-only
strategy that returns +40% while the market returns +60% has destroyed value, and any
report that omits the benchmark makes the strategy look better than it is. L1/L2 are
absolute P&L; L3/L4 are the excess over the market, which is the honest measure of
whether CTREND's ranking added anything on the long side.

Costs use the paper's long-leg rates (30/40/50 bps) against measured turnover. Unlike
the short book there is no borrow or funding leg, so long-only costs are the cleaner
of the two — but market impact in the top quintile is still unmodelled.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

ANN = 52.0
TC_LONG = {"30bps": 0.0030, "40bps": 0.0040, "50bps": 0.0050}


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
    d["L1"] = d["q5"]
    d["L2"] = d["C_long"]
    d["L3"] = d["q5"] - d["mkt"]
    d["L4"] = d["C_long"] - d["C_mkt"]
    d["BM"] = d["mkt"]
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default="reports/m6_variants.csv")
    p.add_argument("--from-year", type=int, default=2024)
    p.add_argument("--to-year", type=int, default=2026)
    p.add_argument("--turnover", type=float, default=0.63,
                   help="weekly turnover of the long leg (gate measured 62.8%)")
    p.add_argument("--detail", action="store_true")
    a = p.parse_args(argv)

    d = build(a.src, a.from_year, a.to_year)
    print(f"\nLong-only books, {a.from_year}–{a.to_year}: {len(d)} weeks "
          f"[{int(d.week.min())} – {int(d.week.max())}]")

    books = [("L1  outright long, all names", d["L1"]),
             ("L2  outright long, LIQUID only", d["L2"]),
             ("L3  market-neutral, all names", d["L3"]),
             ("L4  market-neutral, LIQUID only", d["L4"]),
             ("BM  buy-and-hold the market", d["BM"])]
    t = pd.DataFrame([kpis(s, n) for n, s in books]).set_index("book")
    cols = ["weeks", "total_%", "mean_wk_%", "vol_ann_%", "sharpe", "sortino",
            "max_dd_%", "dd_weeks", "hit_%", "best_%", "worst_%", "skew", "t_stat"]
    print("\n=== GROSS ===")
    print(t[cols].T.to_string(float_format=lambda v: f"{v:9.2f}"))

    print(f"\n=== NET of long-leg transaction costs (turnover {a.turnover:.0%}/wk) ===")
    rows = []
    for label, bps in TC_LONG.items():
        for n, s in (("L1  outright, all", d["L1"]), ("L2  outright, liquid", d["L2"])):
            rows.append(kpis(s - bps * a.turnover, f"{n} @ {label}"))
    rows.append(kpis(d["BM"], "BM  buy-and-hold (no trading)"))
    print(pd.DataFrame(rows).set_index("book")[
        ["total_%", "mean_wk_%", "sharpe", "max_dd_%", "t_stat"]
    ].to_string(float_format=lambda v: f"{v:9.2f}"))

    print("\n=== by calendar year ===")
    print(f"  {'year':>6}{'wks':>5}{'L1 tot%':>10}{'L2 tot%':>10}{'BM tot%':>10}"
          f"{'L1-BM':>9}{'L2 SR':>8}{'L2 maxDD%':>11}")
    for y, s in d.groupby("year"):
        k1, k2, kb = kpis(s["L1"], "1"), kpis(s["L2"], "2"), kpis(s["BM"], "b")
        if "total_%" not in k1:
            continue
        print(f"  {y:>6}{k1['weeks']:>5}{k1['total_%']:>10.1f}{k2['total_%']:>10.1f}"
              f"{kb['total_%']:>10.1f}{k1['total_%'] - kb['total_%']:>9.1f}"
              f"{k2['sharpe']:>8.2f}{k2['max_dd_%']:>11.1f}")

    if a.detail:
        print(f"\n--- week by week (%), {a.from_year}–{a.to_year} ---")
        e1 = (1 + d["L1"]).cumprod()
        e2 = (1 + d["L2"]).cumprod()
        eb = (1 + d["BM"]).cumprod()
        d = d.assign(cum1=(e1 - 1) * 100, cum2=(e2 - 1) * 100, cumb=(eb - 1) * 100,
                     dd2=(e2 / e2.cummax() - 1) * 100)
        print(f"{'week':>7}{'L1':>8}{'L2':>8}{'L3':>8}{'L4':>8}{'BM':>8}"
              f"{'cumL1':>9}{'cumL2':>9}{'cumBM':>9}{'ddL2':>8}{'n':>6}")
        for _, r in d.iterrows():
            def f(v):
                return f"{v * 100:8.2f}" if pd.notna(v) else "     n/a"
            print(f"{int(r['week']):>7}{f(r['L1'])}{f(r['L2'])}{f(r['L3'])}{f(r['L4'])}"
                  f"{f(r['BM'])}{r['cum1']:9.1f}{r['cum2']:9.1f}{r['cumb']:9.1f}"
                  f"{r['dd2']:8.1f}{int(r['n']):6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
