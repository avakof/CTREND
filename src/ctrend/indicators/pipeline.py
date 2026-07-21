"""Daily indicators -> weekly signals -> cross-sectional ranks (SPEC §4.2, M2).

Three steps, in the authors' order:

1. Compute the 28 indicators on the **daily** panel, per coin, after the truncation
   cascade and before the weekly market-cap floor (`b02` computes, `b05` filters).
2. Resample to Liu year-blocks taking **`last`** with ``min_obs = 1`` — the rule
   `b02:240-328` applies to all 28 indicators (returns use `prod`/`'all'`, volume
   uses `sum`, both handled in `ingest/curate.py`).
3. Map each indicator to its **cross-sectional rank** within the week, rescaled to
   ``[-0.5, +0.5]`` exactly as `fCrossSectTransChars.m:48-50` does:
   ``tiedrank`` -> ``(r-1)/(max-1)`` -> ``- 0.5``. Ranks are mean-zero by
   construction, which is why the combining step needs no separate demeaning of the
   regressors (GT-11).

Coverage of the four high/low indicators is carried through as `n_available` rather
than being silently absorbed: under the authors' complete-case rule a coin-week with
any NaN indicator drops out of CTREND entirely, and that loss is ~98% concentrated in
delisted coins. Downstream code must be able to see it.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ctrend.indicators.technical import INDICATORS, NEEDS_HIGH_LOW, compute_indicators

OUT = Path("data/curated/signals_weekly.parquet")
log = logging.getLogger("indicators")


def _liu_week(dates: pd.Series) -> pd.Series:
    """GT-1 week id as YYYYWW; week 52 absorbs the year's remainder."""
    doy = dates.dt.dayofyear
    wk = np.minimum(52, ((doy - 1) // 7) + 1)
    return dates.dt.year.astype("int64") * 100 + wk.astype("int64")


def rank_map(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Cross-sectional rank within each week, rescaled to [-0.5, +0.5].

    `tiedrank` averages ties, and a week whose cross-section is constant (max == 1)
    would divide by zero; those become 0.0, the midpoint, rather than inf.
    """
    out = df.copy()
    g = out.groupby("week_id", sort=False)
    for c in cols:
        r = g[c].rank(method="average")
        n = g[c].transform("count")
        denom = (n - 1).where(n > 1, np.nan)
        out[c] = ((r - 1) / denom - 0.5).fillna(0.0).where(out[c].notna(), np.nan)
    return out


def apply_universe_mask(wk: pd.DataFrame, mask_path: str) -> pd.DataFrame:
    """Restrict to coins with a live venue as of each week (U1).

    The predicate is the interval ``onboard_week <= week_id <= offboard_week``, an
    as-of comparison against per-coin scalars that are facts of the past at every
    week in range — no look-ahead.

    This is applied BEFORE :func:`rank_map`, which is the whole point: ranks must be
    computed *inside* the traded universe. A coin ranked 0.5 among 1,800 names is not
    the coin ranked 0.5 among 400, so filtering after ranking would be a different
    (and much weaker) experiment.
    """
    m = pd.read_parquet(mask_path)
    if "offboard_week" not in m.columns:
        m["offboard_week"] = 999999
    m = m[["coin_id", "onboard_week", "offboard_week"]]
    before, n_before = len(wk), wk["coin_id"].nunique()
    wk = wk.merge(m, on="coin_id", how="inner")
    wk = wk[(wk["week_id"] >= wk["onboard_week"]) & (wk["week_id"] <= wk["offboard_week"])]
    wk = wk.drop(columns=["onboard_week", "offboard_week"]).reset_index(drop=True)
    log.info("universe mask: %s -> %s coin-weeks, %s -> %s coins",
             f"{before:,}", f"{len(wk):,}", f"{n_before:,}", f"{wk['coin_id'].nunique():,}")
    return wk


def build(daily: str = "data/curated/panel_daily.parquet",
          weekly: str = "data/curated/panel_weekly.parquet",
          out: Path = OUT,
          universe_mask: str | None = None) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    # Only coins that reach the weekly panel need indicators, but each needs its
    # FULL daily history for warm-up -- including days below the market-cap floor.
    coins = [r[0] for r in con.execute(
        f"SELECT DISTINCT coin_id FROM read_parquet('{weekly}')").fetchall()]
    log.info("computing 28 indicators for %s coins", f"{len(coins):,}")

    d = con.execute(f"""
        SELECT coin_id, date, close, dollar_volume, high, low
        FROM read_parquet('{daily}')
        WHERE coin_id IN (SELECT DISTINCT coin_id FROM read_parquet('{weekly}'))
        ORDER BY coin_id, date
    """).df()
    d["date"] = pd.to_datetime(d["date"])

    frames = []
    for i, (cid, grp) in enumerate(d.groupby("coin_id", sort=False), 1):
        if grp["close"].notna().sum() < 2:
            continue
        frames.append(compute_indicators(grp))
        if i % 500 == 0:
            log.info("  %d/%d coins", i, len(coins))
    if not frames:
        raise RuntimeError("no indicators computed")
    ind = pd.concat(frames, ignore_index=True)
    log.info("daily indicator rows: %s", f"{len(ind):,}")

    # --- weekly resample: `last` with min_obs = 1 (b02:240-328) -------------
    ind["week_id"] = _liu_week(ind["date"])
    ind = ind.sort_values(["coin_id", "date"])
    wk = ind.groupby(["coin_id", "week_id"], as_index=False)[list(INDICATORS)].last()

    # Keep only coin-weeks that survived the universe filters.
    con.register("wk", wk)
    wk = con.execute(f"""
        SELECT wk.* FROM wk
        JOIN read_parquet('{weekly}') p USING (coin_id, week_id)
    """).df()
    log.info("weekly signal rows: %s", f"{len(wk):,}")

    if universe_mask:
        wk = apply_universe_mask(wk, universe_mask)

    # Availability, carried explicitly (see module docstring).
    cols = list(INDICATORS)
    wk["n_available"] = wk[cols].notna().sum(axis=1)
    wk["has_hl"] = wk[list(NEEDS_HIGH_LOW)].notna().all(axis=1)
    wk["complete_case"] = wk["n_available"] == len(INDICATORS)

    # Belt and braces: an infinity must never reach the rank map. Ranks are
    # *relative*, so a single inf silently pushes every other coin in that week
    # down one place and corrupts the whole cross-section rather than one cell.
    # The upstream cause (close <= 0) is fixed in ingest/curate.py; this guard
    # makes any recurrence loud instead of plausible.
    n_inf = int(np.isinf(wk[cols].to_numpy(dtype="float64")).sum())
    if n_inf:
        log.warning("%s non-finite indicator values -> NaN before ranking "
                    "(expected 0; investigate upstream)", f"{n_inf:,}")
        wk[cols] = wk[cols].replace([np.inf, -np.inf], np.nan)
        wk["n_available"] = wk[cols].notna().sum(axis=1)
        wk["has_hl"] = wk[list(NEEDS_HIGH_LOW)].notna().all(axis=1)
        wk["complete_case"] = wk["n_available"] == len(INDICATORS)

    ranked = rank_map(wk, cols)
    out.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_parquet(out, index=False, compression="zstd")

    cc = float(ranked["complete_case"].mean())
    log.info("signals -> %s  rows=%s  complete-case=%.1f%%  with H/L=%.1f%%",
             out, f"{len(ranked):,}", 100 * cc, 100 * float(ranked["has_hl"].mean()))
    con.close()
    return {"rows": len(ranked), "complete_case_frac": cc}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--daily", default="data/curated/panel_daily.parquet")
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--universe-mask", default=None,
                   help="restrict to a live-venue universe before ranking (U1)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    build(a.daily, a.weekly, a.out, a.universe_mask)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
