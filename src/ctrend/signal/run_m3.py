"""M3 — run the CS-C-ENet walk-forward over the real curated panel.

Produces one CTREND value per eligible coin per target week, using only data
observable at the signal week (invariant I1, enforced structurally by
`Dataset.asof`). Emits both the per-coin signal and the per-week diagnostics
(selected indicators, lambda, AICc, pooled n) needed to interpret it.

The calendar is built from the curated week axis rather than from `sample.start`,
because the panel deliberately begins ~52 blocks before the paper's first factor
week so the first emission has a full estimation window behind it. Feeding the
engine a shorter calendar would quietly shift every sequential index and put the
reconstruction out of phase with `CTREND.xlsx` by a whole number of weeks.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from ctrend.calendar import LiuYearBlockIndex
from ctrend.config import load_config
from ctrend.data.dataset import Dataset
from ctrend.signal.engine import run

log = logging.getLogger("m3")


def _calendar_from_map(week_map: str) -> tuple[LiuYearBlockIndex, pd.DataFrame]:
    wm = pd.read_parquet(week_map).sort_values("seq")
    lo, hi = int(wm.yyyyww.iloc[0]), int(wm.yyyyww.iloc[-1])

    def block_start(w: int) -> pd.Timestamp:
        return pd.Timestamp(year=w // 100, month=1, day=1) + pd.Timedelta(days=7 * (w % 100 - 1))

    # +6 days lands inside the final block. +7 or more spills into the *next*
    # block, which the calendar then includes and the week_map does not — an
    # off-by-one that would shift every sequential index by a constant.
    cal = LiuYearBlockIndex(block_start(lo), block_start(hi) + pd.Timedelta(days=6))
    if len(cal) != len(wm):
        raise RuntimeError(
            f"calendar has {len(cal)} blocks but week_map has {len(wm)}; the "
            "sequential axis and the calendar must agree exactly or every week "
            "id is off by a constant"
        )
    for s, y in zip(wm.seq.to_numpy()[:: max(1, len(wm) // 20)],
                    wm.yyyyww.to_numpy()[:: max(1, len(wm) // 20)]):
        if cal.week_id(int(s)) != int(y):
            raise RuntimeError(f"calendar/week_map disagree at seq={s}: "
                               f"{cal.week_id(int(s))} vs {y}")
    return cal, wm


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="configs/replication.yaml")
    p.add_argument("--curated", default="data/curated")
    p.add_argument("--out", type=Path, default=Path("data/curated/ctrend_weekly.parquet"))
    p.add_argument("--diag", type=Path, default=Path("reports/m3_diagnostics.csv"))
    p.add_argument("--stability-levels", default="1",
                   help="comma-separated N for U5 selection persistence")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    cfg = load_config(a.config)
    cal, wm = _calendar_from_map(f"{a.curated}/week_map.parquet")
    log.info("calendar verified against week_map: %d blocks, %d -> %d",
             len(cal), int(wm.yyyyww.iloc[0]), int(wm.yyyyww.iloc[-1]))

    ds = Dataset.open(a.curated, cfg, calendar=cal)
    log.info("leakage channels declared open: %s", set(ds.leakage_channels()) or "none")

    rows, diag = [], []
    n_live = 0
    levels = tuple(int(x) for x in a.stability_levels.split(","))
    for cw in run(ds, cfg, stability_levels=levels):
        # The final signal week forecasts a target one block beyond the sample.
        # That is a genuine live forecast, not an error -- but there is no realised
        # return to score it against, so it is counted and dropped rather than
        # silently mapped onto a week that does not exist.
        if int(cw.target_week) > int(cal.last_week):
            n_live += 1
            continue
        yw = cal.week_id(cw.target_week)
        block = {"target_week": int(cw.target_week), "yyyyww": yw,
                 "coin_id": cw.coins, "ctrend": cw.values}
        if cw.values_by_level is not None:
            for i, n in enumerate(cw.levels):
                if n > 1:
                    block[f"ctrend_n{n}"] = cw.values_by_level[:, i]
        rows.append(pd.DataFrame(block))
        diag.append({"target_week": int(cw.target_week), "yyyyww": yw,
                     "n_coins": len(cw.coins), "n_selected": int(cw.selected.size),
                     "selected": " ".join(map(str, cw.selected.tolist())),
                     "lam": cw.lam, "aicc": cw.aicc, "n_pooled": cw.n_pooled})
        if len(diag) % 25 == 0:
            log.info("  %d weeks emitted (latest %d, %d coins, %d selected)",
                     len(diag), yw, len(cw.coins), cw.selected.size)
    ds.close()

    if not rows:
        raise RuntimeError("no CTREND weeks produced")
    out = pd.concat(rows, ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out, index=False, compression="zstd")
    dg = pd.DataFrame(diag)
    a.diag.parent.mkdir(parents=True, exist_ok=True)
    dg.to_csv(a.diag, index=False)

    if n_live:
        log.info("dropped %d live forecast(s) beyond the sample edge (no realised return)", n_live)
    log.info("CTREND -> %s  rows=%s  weeks=%s  %d -> %d",
             a.out, f"{len(out):,}", f"{dg.shape[0]:,}",
             int(dg.yyyyww.iloc[0]), int(dg.yyyyww.iloc[-1]))
    log.info("median indicators selected per week: %.1f  median pooled n: %s",
             dg.n_selected.median(), f"{int(dg.n_pooled.median()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
