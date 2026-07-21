"""The full SPEC §7 acceptance gate for CTREND (M4/M5).

Runs the CTREND H-L portfolio through the same sort/turnover/cost machinery the
canary validated, then evaluates all six immutable bands together. The bands are
read-only: a failure is a STOP and a diagnosis, never a parameter search (I3).
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

from ctrend.portfolio.sorts import sort_portfolios

log = logging.getLogger("gate")

COST_SCHEMES = [(0.0030, 0.0040), (0.0040, 0.0050), (0.0050, 0.0060)]


def load(ctrend: str, weekly: str, start: int, end: int) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, weekly_return,
                   lag(market_cap) OVER (PARTITION BY coin_id ORDER BY week_id) AS mcap_lag
            FROM read_parquet('{weekly}')
        )
        SELECT c.yyyyww AS week, c.coin_id, c.ctrend,
               p.weekly_return AS fwd, p.mcap_lag AS mcap
        FROM read_parquet('{ctrend}') c
        JOIN p ON p.coin_id = c.coin_id AND p.week_id = c.yyyyww
        WHERE p.weekly_return IS NOT NULL AND c.ctrend IS NOT NULL AND p.mcap_lag > 0
          AND c.yyyyww BETWEEN {start} AND {end}
    """).df()
    con.close()
    return df


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ctrend", default="data/curated/ctrend_weekly.parquet")
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--ltw", default="data/curated/ltw_factors.parquet")
    p.add_argument("--shipped",
                   default="data/raw/dataverse_NTIVT8/Results/CTREND/CTREND.xlsx")
    p.add_argument("--start", type=int, default=201516)
    p.add_argument("--end", type=int, default=202222)
    p.add_argument("--out", type=Path, default=Path("reports/m5_gate.csv"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    df = load(a.ctrend, a.weekly, a.start, a.end)
    res = sort_portfolios(df, "ctrend")
    w = res.weekly
    hl = w["hl"]
    n = len(hl)
    mean, sd = hl.mean(), hl.std(ddof=1)
    t = mean / (sd / np.sqrt(n))
    sharpe = mean / sd * np.sqrt(52)
    # Lo (2002): t on the UNannualised Sharpe.
    sr = mean / sd
    lo_t = sr / np.sqrt((1 + 0.5 * sr**2) / n)

    ltw = pd.read_parquet(a.ltw).rename(columns={"yyww": "week"})
    d = w.merge(ltw, on="week", how="inner").dropna(subset=["hl", "cmkt", "csize", "cmom"])
    X = sm.add_constant(d[["cmkt", "csize", "cmom"]].to_numpy())
    f3 = sm.OLS(d["hl"].to_numpy(), X).fit()
    alpha_ltw, t_alpha, b_cmom = f3.params[0], f3.tvalues[0], f3.params[3]

    print("\n" + "=" * 66)
    print("SPEC §7 ACCEPTANCE GATE — CTREND, %d–%d, %d weeks" % (a.start, a.end, n))
    print("=" * 66)
    qs = [w[f"q{k}"].mean() * 100 for k in range(1, 6)]
    print("  quintile means %/wk : " + "  ".join(f"{v:6.2f}" for v in qs))
    mono = all(qs[i] < qs[i + 1] for i in range(4))
    print(f"  turnover %/wk       : {w['turnover'].mean() * 100:6.2f}")
    print(f"  Lo(2002) Sharpe t   : {lo_t:6.2f}")
    print("\n  net of transaction costs (long/short bps):")
    for tcl, tcs in COST_SCHEMES:
        r = sort_portfolios(df, "ctrend", tc_long=tcl, tc_short=tcs).weekly
        nm, nsd = r["hl_net"].mean(), r["hl_net"].std(ddof=1)
        print(f"    {int(tcl * 1e4)}/{int(tcs * 1e4)}: {nm * 100:6.2f}%/wk  "
              f"t={nm / (nsd / np.sqrt(len(r))):5.2f}")
    # Breakeven TC divides by the RAW weight change -- unhalved and not
    # drift-adjusted (`fSingleSortMulti.m:329`) -- which is a different quantity
    # from the reported GKX turnover. Using the GKX figure here inflates the
    # breakeven roughly fourfold (5.63% vs the paper's 1.41%).
    raw_turn = (w["to_long"] + w["to_short"]).mean() * 2.0
    betc = mean / raw_turn if raw_turn > 0 else np.nan
    print(f"  breakeven TC        : {betc * 100:6.2f}%   (paper 1.41; divides by the "
          f"raw unhalved Σ|Δw|, not the GKX turnover)")

    bands = [
        ("quintiles monotone Q1→Q5", float(mono), 1.0, 1.0, "monotone"),
        ("H−L mean %/week", mean * 100, 3.0, 4.7, "3.87"),
        ("annualised Sharpe", sharpe, 1.5, 2.4, "1.94"),
        ("CMOM beta", b_cmom, 0.6, 1.0, "0.79"),
        ("alpha vs LTW %/week", alpha_ltw * 100, 1e-9, np.inf, "2.62"),
        ("alpha vs LTW t-stat", t_alpha, 3.0, np.inf, "4.22"),
        ("weekly turnover %", w["turnover"].mean() * 100, 55.0, 80.0, "68.45"),
    ]
    print("\n  " + "-" * 62)
    n_pass = 0
    for label, val, lo, hi, paper in bands:
        ok = (lo <= val) if np.isinf(hi) else (lo <= val <= hi)
        n_pass += ok
        band = f"> {lo:g}" if np.isinf(hi) else f"[{lo:g}, {hi:g}]"
        shown = "yes" if label.startswith("quintiles") and val == 1.0 else f"{val:.3f}"
        print(f"  {label:<26} {shown:>8}  band {band:<12} paper {paper:<9} "
              f"{'PASS' if ok else 'FAIL'}")
    print("  " + "-" * 62)
    print(f"  {n_pass}/{len(bands)} bands pass")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    w.to_csv(a.out, index=False)
    return 0 if n_pass == len(bands) else 1


if __name__ == "__main__":
    raise SystemExit(main())
