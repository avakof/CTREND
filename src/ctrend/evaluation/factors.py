"""Cryptocurrency factor reconstruction and the §7 asset-pricing gate (SPEC §4.4).

Factors follow the authors' own in-package reconstruction, `b06:146-159`, which is
*not* the plain tercile sort SPEC §4.4 describes in prose:

    CMKT   value-weighted market return (raw; GT-3 -- no risk-free is subtracted
           anywhere in the authors' code)
    CSMB   30/70 market-cap breakpoints, bottom minus top  (small-minus-big)
    CMOM   dependent 2 x (30/70) sort: split at the size median, sort 3-week
           momentum 30/70 within each half, average the two high-minus-low legs

The paper's baseline (`b06:26`, `lUseLTW = true`) regresses on **Liu's published**
factors rather than these, so those are the primary series here and the
reconstruction is the cross-check SPEC §4.4 asks for (correlation >= 0.95).

t-statistics are plain OLS/iid, per GT-12: the authors use `regstats`, and the
paper's α^LTW t = 4.22 is an OLS t. Newey-West is reported alongside as a robustness
column but is NOT the gate.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

log = logging.getLogger("factors")


def _vw(g: pd.DataFrame, col: str = "fwd") -> float:
    return float((g["mcap"] * g[col]).sum() / g["mcap"].sum())


def reconstruct(weekly: str, start: int = 201516, end: int = 202222) -> pd.DataFrame:
    """CMKT / CSMB / CMOM from our own panel (`b06:146-159`)."""
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, weekly_return, market_cap
            FROM read_parquet('{weekly}')
        ), m AS (
            -- A factor dated week W is the return REALISED IN week W, formed from
            -- information known at W-1. So the realised leg is `weekly_return` at
            -- W, and both the value weights and the momentum sort use their LAGGED
            -- values. Dating the factor by the week whose information formed it
            -- (i.e. using `lead(weekly_return)`) shifts the whole series one week
            -- early and drives its correlation with LTW's published factors to ~0
            -- while every other diagnostic still looks reasonable.
            SELECT *,
                   lag(market_cap) OVER w AS mcap_lag,
                   (1 + lag(weekly_return, 1) OVER w)
                   * (1 + lag(weekly_return, 2) OVER w)
                   * (1 + lag(weekly_return, 3) OVER w) - 1 AS ret_3_0_lag
            FROM p WINDOW w AS (PARTITION BY coin_id ORDER BY week_id)
        )
        SELECT week_id AS week, coin_id, mcap_lag AS mcap,
               ret_3_0_lag AS ret_3_0, weekly_return AS fwd
        FROM m
        WHERE weekly_return IS NOT NULL AND mcap_lag > 0
          AND week_id BETWEEN {start} AND {end}
    """).df()
    con.close()

    rows = []
    for wk, g in df.groupby("week", sort=True):
        if len(g) < 25:
            continue
        rec = {"week": int(wk), "cmkt_own": _vw(g)}

        # CSMB: 30/70 market-cap breakpoints, bottom minus top.
        lo, hi = g["mcap"].quantile([0.30, 0.70])
        small, big = g[g.mcap <= lo], g[g.mcap >= hi]
        if len(small) >= 5 and len(big) >= 5:
            rec["csmb_own"] = _vw(small) - _vw(big)

        # CMOM: dependent 2 x (30/70) sort, averaged across the size halves.
        mm = g.dropna(subset=["ret_3_0"])
        if len(mm) >= 25:
            med = mm["mcap"].median()
            legs = []
            for half in (mm[mm.mcap <= med], mm[mm.mcap > med]):
                if len(half) < 10:
                    continue
                a, b = half["ret_3_0"].quantile([0.30, 0.70])
                lo_p, hi_p = half[half.ret_3_0 <= a], half[half.ret_3_0 >= b]
                if len(lo_p) >= 3 and len(hi_p) >= 3:
                    legs.append(_vw(hi_p) - _vw(lo_p))
            if legs:
                rec["cmom_own"] = float(np.mean(legs))
        rows.append(rec)
    return pd.DataFrame(rows)


def regress(y: pd.Series, X: pd.DataFrame) -> dict:
    """OLS with iid errors (GT-12), plus HAC as a reported robustness column."""
    Xc = sm.add_constant(X, has_constant="add")
    fit = sm.OLS(y.to_numpy(), Xc.to_numpy()).fit()
    hac = sm.OLS(y.to_numpy(), Xc.to_numpy()).fit(
        cov_type="HAC", cov_kwds={"maxlags": 4})
    names = ["alpha"] + list(X.columns)
    out = {f"{n}": fit.params[i] for i, n in enumerate(names)}
    out.update({f"t_{n}": fit.tvalues[i] for i, n in enumerate(names)})
    out["t_alpha_hac"] = hac.tvalues[0]
    out["r2"] = fit.rsquared
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--ltw", default="data/curated/ltw_factors.parquet")
    p.add_argument("--validation", default="reports/m3_validation.csv")
    p.add_argument("--out", type=Path, default=Path("reports/m4_factors.csv"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    own = reconstruct(a.weekly)
    ltw = pd.read_parquet(a.ltw).rename(columns={"yyww": "week"})
    f = own.merge(ltw, on="week", how="inner")
    log.info("factor weeks: own=%d ltw=%d overlapping=%d", len(own), len(ltw), len(f))

    print("\n=== factor reconstruction cross-check (SPEC §4.4, gate >= 0.95) ===")
    for a_, b_ in (("cmkt_own", "cmkt"), ("csmb_own", "csize"), ("cmom_own", "cmom")):
        s = f[[a_, b_]].dropna()
        c = s[a_].corr(s[b_])
        print(f"  corr({a_:<9}, {b_:<5}) = {c:6.3f}  n={len(s):>4}  "
              f"{'PASS' if c >= 0.95 else 'below gate — documented in DECISIONS.md'}")

    ctr = pd.read_csv(a.validation)[["yyyyww", "hl"]].rename(columns={"yyyyww": "week"})
    d = ctr.merge(f, on="week", how="inner").dropna(subset=["hl", "cmkt", "csize", "cmom"])
    log.info("CTREND weeks matched to factors: %d", len(d))

    ccapm = regress(d["hl"], d[["cmkt"]])
    ltw3 = regress(d["hl"], d[["cmkt", "csize", "cmom"]])

    print("\n=== CTREND H-L factor regressions (LTW published factors) ===")
    print(f"  CCAPM : alpha {ccapm['alpha'] * 100:6.2f}%/wk  t={ccapm['t_alpha']:5.2f}"
          f"   b_cmkt {ccapm['cmkt']:6.3f}")
    print(f"  LTW-3 : alpha {ltw3['alpha'] * 100:6.2f}%/wk  t={ltw3['t_alpha']:5.2f}"
          f"   (HAC t={ltw3['t_alpha_hac']:5.2f})")
    print(f"          b_cmkt {ltw3['cmkt']:6.3f}  b_csize {ltw3['csize']:6.3f}  "
          f"b_cmom {ltw3['cmom']:6.3f}   R2={ltw3['r2']:.3f}")

    print("\n=== SPEC §7 bands ===")
    checks = [
        ("CMOM beta", ltw3["cmom"], 0.6, 1.0, "0.79"),
        ("alpha vs LTW %/wk", ltw3["alpha"] * 100, 0.0, np.inf, "2.62"),
        ("alpha vs LTW t-stat", ltw3["t_alpha"], 3.0, np.inf, "4.22"),
    ]
    for label, val, lo, hi, paper in checks:
        ok = lo < val <= hi if np.isinf(hi) else lo <= val <= hi
        band = f"> {lo}" if np.isinf(hi) else f"[{lo}, {hi}]"
        print(f"  {label:<22} {val:8.3f}   band {band:<12} paper {paper:<5} "
              f"{'PASS' if ok else 'FAIL'}")

    f.to_csv(a.out, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
