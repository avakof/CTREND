"""Adapt the M1/M2 outputs into the curated layout `Dataset` reads (M3).

`data/curated/panel_weekly.parquet` + `signals_weekly.parquet` carry `YYYYWW` week
ids, which are the paper's convention and the shipped factor's. The signal engine
instead indexes weeks by a **dense sequential integer** so that `Dataset.asof(w)`
maps onto hive partitions and "never open a future file" is a physical property of
the scan rather than a promise (see `data/schema.py`).

This module is the only place the two conventions meet. It writes:

    data/curated/panel/week_id=NNNN/part.parquet   z0..z27 + prices/returns
    data/curated/coin_registry.parquet
    data/curated/delisting_registry.parquet
    data/curated/week_map.parquet                  seq <-> YYYYWW, both directions

`week_map` is written because every downstream comparison against the authors'
`CTREND.xlsx` needs to travel back from the engine's sequential index to `YYYYWW`;
reconstructing that mapping ad hoc is exactly how an off-by-one week enters a
replication unnoticed.

The sequential axis spans **every** Liu block between the panel's first and last
week, including blocks with no surviving coins. A dense axis is required: the
walk-forward's 52-week window counts *calendar* blocks, so silently compressing
empty weeks would shorten the estimation window without saying so.

Excess return is `weekly_return - risk_free`, and `risk_free = 0` per GT-3 (the
authors construct a risk-free series and then never read it), so the two are equal
by construction here. The column is kept distinct because SPEC §4.3 regresses on
excess returns and a future config could set it non-zero.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

import duckdb
import pandas as pd

from ctrend.indicators.technical import INDICATORS

OUT = Path("data/curated")
log = logging.getLogger("to_curated")


def _week_axis(lo: int, hi: int) -> list[int]:
    """Every Liu `YYYYWW` block from `lo` to `hi` inclusive, dense."""
    out = []
    for y in range(lo // 100, hi // 100 + 1):
        for k in range(1, 53):
            w = y * 100 + k
            if lo <= w <= hi:
                out.append(w)
    return out


def build(weekly: str = "data/curated/panel_weekly.parquet",
          signals: str = "data/curated/signals_weekly.parquet",
          registry: str = "data/curated/universe_registry.parquet",
          out: Path = OUT, risk_free: float = 0.0,
          week_axis_from: str | None = None) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    # The sequential axis must be IDENTICAL across curated roots, otherwise the
    # same seq index means a different calendar week in each and side-by-side
    # comparison is silently wrong. A restricted universe therefore takes its axis
    # from the unrestricted panel.
    axis_src = week_axis_from or weekly
    lo, hi = con.execute(
        f"SELECT min(week_id), max(week_id) FROM read_parquet('{axis_src}')").fetchone()
    axis = _week_axis(int(lo), int(hi))
    wmap = pd.DataFrame({"seq": range(len(axis)), "yyyyww": axis})
    log.info("week axis: %s blocks, %s -> %s", len(axis), lo, hi)

    con.register("wmap", wmap)
    zsel = ", ".join(f's."{name}" AS z{j}' for j, name in enumerate(INDICATORS))
    panel = con.execute(f"""
        SELECT CAST(m.seq AS INTEGER) AS week_id,
               CAST(p.coin_id AS BIGINT) AS coin_id,
               p.close, p.dollar_volume, p.market_cap,
               p.weekly_return,
               p.weekly_return - {risk_free} AS excess_return,
               {zsel}
        FROM read_parquet('{weekly}') p
        JOIN read_parquet('{signals}') s USING (coin_id, week_id)
        JOIN wmap m ON m.yyyyww = p.week_id
        ORDER BY week_id, coin_id
    """).df()
    log.info("curated panel rows: %s", f"{len(panel):,}")

    pdir = out / "panel"
    if pdir.exists():
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)
    for wk, g in panel.groupby("week_id", sort=True):
        d = pdir / f"week_id={int(wk):04d}"
        d.mkdir()
        g.drop(columns=["week_id"]).to_parquet(d / "part.parquet", index=False,
                                               compression="zstd")

    # Derive the registry from the panel we actually wrote. Reusing the global
    # universe_registry would give a coin its UNMASKED first_week: under a
    # restricted universe that seq can precede any row the coin actually has, and
    # `dataset._pivot_and_freeze` then silently discards rows for coins missing
    # from the axis. No error, no warning, wrong universe.
    con.register("panel_df", panel[["coin_id", "week_id"]])
    reg = con.execute(f"""
        WITH span AS (
            SELECT coin_id, min(week_id) AS first_seen_week FROM panel_df GROUP BY 1
        )
        SELECT CAST(s.coin_id AS BIGINT) AS coin_id,
               COALESCE(CAST(r.symbol AS VARCHAR), 'NA') AS symbol,
               CAST(s.first_seen_week AS INTEGER) AS first_seen_week
        FROM span s LEFT JOIN read_parquet('{registry}') r USING (coin_id)
        ORDER BY coin_id
    """).df()
    if reg["coin_id"].nunique() != panel["coin_id"].nunique():
        raise RuntimeError(
            f"registry/panel coin mismatch: {reg['coin_id'].nunique()} vs "
            f"{panel['coin_id'].nunique()} — coins would be silently dropped by "
            "Dataset._pivot_and_freeze"
        )
    reg.to_parquet(out / "coin_registry.parquet", index=False)

    # A delisting is recorded only for coins that actually stop; a survivor has no
    # last trade week, and inventing one would make the registry lie about the
    # sample's right edge.
    last_seq = int(panel["week_id"].max())
    dl = con.execute("""
        WITH span AS (SELECT coin_id, max(week_id) AS last_trade_week
                      FROM panel_df GROUP BY 1)
        SELECT CAST(coin_id AS BIGINT) AS coin_id,
               CAST(last_trade_week AS INTEGER) AS last_trade_week,
               CAST(NULL AS DOUBLE) AS last_price,
               'no_further_observations' AS reason
        FROM span WHERE last_trade_week < ?
        ORDER BY coin_id
    """, [last_seq]).df()
    dl.to_parquet(out / "delisting_registry.parquet", index=False)
    wmap.to_parquet(out / "week_map.parquet", index=False)

    (out / "_provenance.json").write_text(json.dumps({
        "source": "CMC daily snapshots + CMC per-coin OHLC + Gandal CC0 OHLC",
        "weeks": len(axis), "first_yyyyww": int(lo), "last_yyyyww": int(hi),
        "rows": int(len(panel)), "coins": int(panel.coin_id.nunique()),
        "risk_free": risk_free,
    }, indent=2))

    log.info("curated -> %s  weeks=%s coins=%s  delisted=%s",
             out, len(axis), f"{panel.coin_id.nunique():,}", f"{len(dl):,}")
    con.close()
    return {"weeks": len(axis), "rows": len(panel),
            "coins": int(panel.coin_id.nunique()), "delisted": len(dl)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--risk-free", type=float, default=0.0)
    p.add_argument("--signals", default="data/curated/signals_weekly.parquet")
    p.add_argument("--week-axis-from", default=None,
                   help="take the sequential week axis from this panel (U1)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    build(signals=a.signals, out=a.out, risk_free=a.risk_free,
          week_axis_from=a.week_axis_from)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
