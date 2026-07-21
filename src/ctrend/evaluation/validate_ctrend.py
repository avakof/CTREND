"""M3 validation — the reconstructed CTREND factor vs the authors' shipped series.

`Results/CTREND/CTREND.xlsx` in the replication package contains the paper's own
371 weekly H−L factor returns (201516 → 202222), verified at mean 3.866%/week and
Sharpe 1.944 against the published 3.87 / 1.94.

That makes it a far sharper instrument than the SPEC §7 acceptance bands. A band
asks "did you land in a range"; a week-by-week correlation asks "did you reproduce
*this* series", and it fails loudly on a one-week phase error, an inverted sign, or a
signal that is merely plausible on average. Both are reported — the bands remain the
formal gate — but the correlation is the diagnostic that localises a defect.

The factor is rebuilt exactly as Table 3 does: value-weighted quintiles on CTREND,
long the top, short the bottom, held one week, with the `fSingleSortMulti.m` cross-
section minimums.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ctrend.evaluation.table2_gate import _matlab_quantile, MIN_ASSETS, MIN_CS, N_Q

SHIPPED = "data/raw/dataverse_NTIVT8/Results/CTREND/CTREND.xlsx"
log = logging.getLogger("validate")


def hl_factor(ctrend: str, weekly: str) -> pd.DataFrame:
    """Value-weighted quintile H−L on CTREND, plus the quintile means."""
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    # ALIGNMENT, and the one thing most likely to be got wrong here.
    # `engine.run` sets `target_week = signal_week + 1` and CTREND at target T is
    # the forecast **of week T's return**. So the realised return to score it
    # against is week T's own, and the value weights are the ones known when the
    # portfolio is formed -- i.e. week T-1's market cap, matching the lagged
    # weighting the authors use at `b05:153`.
    #
    # Taking `lead(weekly_return)` here instead scores the forecast one week late
    # and collapses the correlation to ~0 while leaving every summary statistic
    # superficially plausible.
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, weekly_return,
                   lag(market_cap) OVER (PARTITION BY coin_id ORDER BY week_id) AS mcap_lag
            FROM read_parquet('{weekly}')
        )
        SELECT c.yyyyww, c.coin_id, c.ctrend,
               p.mcap_lag AS market_cap, p.weekly_return AS fwd
        FROM read_parquet('{ctrend}') c
        JOIN p ON p.coin_id = c.coin_id AND p.week_id = c.yyyyww
        WHERE p.weekly_return IS NOT NULL AND c.ctrend IS NOT NULL
          AND p.mcap_lag > 0
    """).df()
    con.close()

    rows = []
    for wk, g in df.groupby("yyyyww", sort=True):
        if len(g) < MIN_CS:
            continue
        cuts = _matlab_quantile(g["ctrend"].to_numpy(), np.linspace(0, 1, N_Q + 1))
        q = np.searchsorted(cuts[1:-1], g["ctrend"].to_numpy(), side="left")
        g = g.assign(q=q)
        means = {}
        for k in range(N_Q):
            s = g[g.q == k]
            means[f"q{k + 1}"] = (np.average(s["fwd"], weights=s["market_cap"])
                                  if len(s) >= MIN_ASSETS else np.nan)
        if np.isnan(means["q1"]) or np.isnan(means[f"q{N_Q}"]):
            continue
        rows.append({"yyyyww": int(wk), **means,
                     "hl": means[f"q{N_Q}"] - means["q1"]})
    return pd.DataFrame(rows).sort_values("yyyyww").reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ctrend", default="data/curated/ctrend_weekly.parquet")
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--shipped", default=SHIPPED)
    p.add_argument("--out", type=Path, default=Path("reports/m3_validation.csv"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    mine = hl_factor(a.ctrend, a.weekly)
    ship = pd.read_excel(a.shipped, sheet_name="Data from Study")
    ship.columns = ["yyyyww", "shipped"]
    j = mine.merge(ship, on="yyyyww", how="inner")
    log.info("weeks: mine=%d shipped=%d overlapping=%d", len(mine), len(ship), len(j))

    m, s = j["hl"], j["shipped"]
    ann = np.sqrt(52)
    stats = {
        "overlap_weeks": len(j),
        "mine_mean_pct": m.mean() * 100, "shipped_mean_pct": s.mean() * 100,
        "mine_sd_pct": m.std(ddof=1) * 100, "shipped_sd_pct": s.std(ddof=1) * 100,
        "mine_sharpe": m.mean() / m.std(ddof=1) * ann,
        "shipped_sharpe": s.mean() / s.std(ddof=1) * ann,
        "pearson": m.corr(s), "spearman": m.corr(s, method="spearman"),
        "sign_agreement": float((np.sign(m) == np.sign(s)).mean()),
        "mine_t": m.mean() / (m.std(ddof=1) / np.sqrt(len(m))),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    j.to_csv(a.out, index=False)

    print("\n=== M3: reconstructed CTREND vs the authors' shipped factor ===")
    for k, v in stats.items():
        print(f"  {k:<20} {v:>10.3f}" if isinstance(v, float) else f"  {k:<20} {v:>10}")
    print("\n  quintile means (%/week, value-weighted):")
    for k in [f"q{i}" for i in range(1, N_Q + 1)]:
        print(f"    {k}: {mine[k].mean() * 100:6.2f}")
    mono = all(mine[f"q{i}"].mean() < mine[f"q{i + 1}"].mean() for i in range(1, N_Q))
    print(f"    monotone Q1->Q5: {mono}")

    print("\n  SPEC §7 bands (formal gate):")
    for label, val, lo, hi in [
        ("H-L mean %/wk", stats["mine_mean_pct"], 3.0, 4.7),
        ("annualised Sharpe", stats["mine_sharpe"], 1.5, 2.4),
    ]:
        ok = lo <= val <= hi
        print(f"    {label:<20} {val:7.3f}   band [{lo}, {hi}]  {'PASS' if ok else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
