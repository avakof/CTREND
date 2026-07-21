"""M4 pipeline canary — 3-week momentum, run BEFORE CTREND is judged (SPEC §6).

    "the 3-week-momentum quintile H-L on Track A lands in 2.0-4.0%/week
     (paper: 3.06) *before* CTREND is judged — this validates the pipeline
     independently of the novel signal."

The point is separation of concerns: momentum is a trivially-defined, well-known
signal, so if the sort/weighting/turnover machinery is wrong the canary fails and the
fault is unambiguously in the pipeline rather than in CS-C-ENet. Judging CTREND first
would confound the two.

`ret_3_0` is the cumulative return over the previous 3 weeks (`b15`/`Table 4`
convention), formed at week *t* and held over week *t+1*.
"""
from __future__ import annotations

import argparse
import logging
import sys

import duckdb
import numpy as np

from ctrend.portfolio.sorts import sort_portfolios

log = logging.getLogger("canary")

BAND = (2.0, 4.0)
PAPER = 3.06


def build(weekly: str, start: int = 201516, end: int = 202222):
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, weekly_return, market_cap,
                   row_number() OVER (PARTITION BY coin_id ORDER BY week_id) AS rn
            FROM read_parquet('{weekly}')
        ), m AS (
            SELECT *,
                   -- 3-week momentum formed at t: product of returns t-2..t.
                   (1 + weekly_return)
                   * (1 + lag(weekly_return, 1) OVER w)
                   * (1 + lag(weekly_return, 2) OVER w) - 1 AS ret_3_0,
                   lead(weekly_return) OVER w AS fwd,
                   lead(week_id)       OVER w AS nxt
            FROM p
            WINDOW w AS (PARTITION BY coin_id ORDER BY week_id)
        )
        SELECT week_id AS week, coin_id, ret_3_0, fwd, market_cap AS mcap
        FROM m
        WHERE ret_3_0 IS NOT NULL AND fwd IS NOT NULL AND market_cap > 0
          AND nxt IS NOT NULL AND week_id BETWEEN {start} AND {end}
    """).df()
    con.close()
    return df


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    df = build(a.weekly)
    log.info("canary panel: %s coin-weeks, %s weeks", f"{len(df):,}", df.week.nunique())
    res = sort_portfolios(df, "ret_3_0")
    w = res.weekly
    hl = w["hl"]
    mean = hl.mean() * 100
    t = hl.mean() / (hl.std(ddof=1) / np.sqrt(len(hl)))

    print("\n=== M4 canary: 3-week momentum quintile H-L ===")
    print(f"  weeks                {len(hl):>8}")
    for k in range(1, 6):
        print(f"  q{k} mean %/wk        {w[f'q{k}'].mean() * 100:>8.2f}")
    print(f"  H-L mean %/wk        {mean:>8.2f}   (paper {PAPER})")
    print(f"  t-statistic          {t:>8.2f}")
    print(f"  Sharpe (annualised)  {hl.mean() / hl.std(ddof=1) * np.sqrt(52):>8.2f}")
    print(f"  weekly turnover %    {w['turnover'].mean() * 100:>8.2f}")
    ok = BAND[0] <= mean <= BAND[1]
    print(f"\n  GATE  band {BAND}  ->  {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("  A canary failure implicates the sort/weight/turnover machinery,")
        print("  NOT the CS-C-ENet signal. Diagnose here before judging CTREND.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
