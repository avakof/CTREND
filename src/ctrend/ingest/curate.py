"""Curate the raw CMC daily snapshots into the weekly panel (SPEC §4.1, M1).

Order of operations is load-bearing and follows the authors' scripts exactly. The
filters are *not* interchangeable: two of them run on the DAILY panel before any
weekly aggregation, and one runs weekly afterwards.

    b01ReadData.m:52      daily simple returns from close, no delisting adjustment
    b01ReadData.m:59-62   drop mME <= 0 and mME > Bitcoin's       [DAILY]
    b02:66-74             truncate returns 0.5/99.5 per-day cross-sectionally,
                          setting outliers to NaN                  [DAILY, GT-2]
    b02:76-81             the truncated coin-day is wiped from close, and
                          fEnsureAllObs cascades that to mcap/volume/OHLC
    fResampleLiuEtAl.m    weekly blocks: Jan 1 + 7d, 52/yr, wk52 absorbs the
                          remainder                                [GT-1]
    b02:240-328           per-series aggregation: returns prod(1+r)-1 with
                          min_obs='all', close/mcap last, volume sum
    b05:62-74             weekly mcap >= 1e6, price floor, stablecoin exclusion

Two quirks are reproduced deliberately, both flagged in DECISIONS.md:

* ``first_obs_quirk: faithful`` — MATLAB's ``NaN ~= NaN`` is true, so `lChanged`
  at `b02:76` fires on cells that were *already* NaN, which includes every coin's
  first day (its return is NaN by construction). Every coin therefore loses its
  first observation. Reproduced for bit-comparability; ``corrected`` disables it.
* The mcap > Bitcoin screen is keyed on CMC asset id 1 and framed by the authors
  as data-error removal, not an economic screen.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import pandas as pd

BTC_ID = 1  # CMC asset id, hard-coded in b01ReadData.m:59-62
RAW_GLOB = "data/raw/cmc_daily/**/*.parquet"
OUT_ROOT = Path("data/curated")

log = logging.getLogger("curate")


def _liu_week_sql(col: str = "date") -> str:
    """GT-1 week id as YYYYWW. Week 52 absorbs days 358..365/366."""
    return (
        f"CAST(year({col}) AS BIGINT) * 100 + "
        f"LEAST(52, CAST(floor((dayofyear({col}) - 1) / 7) AS BIGINT) + 1)"
    )


def curate(cfg, raw_glob: str = RAW_GLOB, out_root: Path = OUT_ROOT,
           ohlc_root: str | Path = "data/raw/cmc_ohlc",
           gandal_path: str | Path = "data/curated/gandal_ohlc.parquet") -> dict:
    out_root.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    lo = float(cfg.returns.truncate_lower_pct)
    hi = float(cfg.returns.truncate_upper_pct)
    faithful = cfg.returns.first_obs_quirk == "faithful"

    log.info("loading raw daily panel ...")
    # De-duplicate (coin_id, date). The harvest crashed once mid-run and the
    # crash-and-resume left 4 dates in 2020 written twice (11,445 rows). A
    # duplicated coin-day is not a harmless extra row: the weekly aggregation
    # requires `n_ret == block_days` (min_obs='all'), so a doubled day makes the
    # count 8 instead of 7 and voids the ENTIRE coin-week. Those four dates
    # collapsed four weekly cross-sections from ~900 coins to ~18, and because a
    # skipped week makes the 52-week smoothing window incomplete, each collapse
    # then suppressed the next 52 CTREND emissions.
    con.execute(f"""
        CREATE TEMP TABLE daily AS
        SELECT * EXCLUDE (rn) FROM (
        SELECT id AS coin_id, name, symbol, slug, date,
               price, marketCap AS market_cap, volume24h AS dollar_volume,
               is_stablecoin, cmcRank AS cmc_rank,
               row_number() OVER (PARTITION BY id, date ORDER BY marketCap DESC) AS rn
        FROM read_parquet('{raw_glob}')
        -- A non-positive price is a data error, treated exactly as `b01ReadData.m:59-62`
        -- treats a non-positive market cap. CMC reports 0.0 for sub-denormal meme-token
        -- prices; left in, `close = 0` makes the daily return 0/0 and every
        -- `sma_Xd = SMA(close)/close` infinite, and the infinity survives the rank map
        -- to corrupt whole cross-sections. Distinct from `min_price_usd`, which is the
        -- authors' economic filter (dMinPrc) and applies weekly.
        WHERE price IS NOT NULL AND price > 0
        ) WHERE rn = 1
    """)

    # --- DAILY filter 1: b01ReadData.m:59-62 -------------------------------
    # mME <= 0 or mME > Bitcoin's, applied per DAY against that day's BTC.
    con.execute(f"""
        CREATE TEMP TABLE btc AS
        SELECT date, max(market_cap) AS btc_mcap
        FROM daily WHERE coin_id = {BTC_ID} GROUP BY date
    """)
    con.execute("""
        CREATE TEMP TABLE d1 AS
        SELECT d.*, b.btc_mcap,
               CASE WHEN d.market_cap <= 0 OR b.btc_mcap IS NULL
                         OR d.market_cap > b.btc_mcap
                    THEN NULL ELSE d.market_cap END AS mcap_ok
        FROM daily d LEFT JOIN btc b USING (date)
    """)

    # --- daily returns from close (b01ReadData.m:52) -----------------------
    con.execute("""
        CREATE TEMP TABLE d2 AS
        SELECT *,
               price / lag(price) OVER (PARTITION BY coin_id ORDER BY date) - 1 AS ret
        FROM d1
    """)

    # --- DAILY filter 2: GT-2 per-day cross-sectional truncation -----------
    # Quantiles over each day's own cross-section; outliers become NaN (dropped),
    # they are NOT clipped. No look-ahead: each day sees only itself.
    con.execute(f"""
        CREATE TEMP TABLE bounds AS
        SELECT date,
               quantile_cont(ret, {lo}) AS lo_b,
               quantile_cont(ret, {hi}) AS hi_b
        FROM d2 WHERE ret IS NOT NULL AND mcap_ok IS NOT NULL
        GROUP BY date
    """)
    con.execute("""
        CREATE TEMP TABLE d3 AS
        SELECT d.*, b.lo_b, b.hi_b,
               CASE WHEN d.ret IS NULL THEN NULL
                    WHEN d.ret < b.lo_b OR d.ret > b.hi_b THEN NULL
                    ELSE d.ret END AS ret_trunc
        FROM d2 d LEFT JOIN bounds b USING (date)
    """)

    # --- the cascade: b02:76-81 + fEnsureAllObs ----------------------------
    # A truncated coin-day is wiped from price, and that deletion propagates to
    # market cap and volume. `changed` reproduces MATLAB NaN ~= NaN when faithful.
    changed = ("(d.ret IS DISTINCT FROM d.ret_trunc) OR d.ret IS NULL"
               if faithful else "(d.ret IS NOT NULL AND d.ret_trunc IS NULL)")
    con.execute(f"""
        CREATE TEMP TABLE d4 AS
        SELECT coin_id, name, symbol, slug, date, is_stablecoin, cmc_rank,
               CASE WHEN {changed} THEN NULL ELSE price END      AS close,
               CASE WHEN {changed} THEN NULL ELSE mcap_ok END    AS market_cap,
               CASE WHEN {changed} THEN NULL ELSE dollar_volume END AS dollar_volume,
               ret_trunc AS ret
        FROM d3 d
    """)

    # --- join daily high/low, and persist the DAILY panel -------------------
    # Indicators are computed on the daily panel *after* the truncation cascade
    # and *before* the weekly mcap floor (b02 computes, b05 filters).
    #
    # Only `high` and `low` are taken from the per-coin OHLC endpoint. Its close,
    # volume and market cap are deliberately ignored: that endpoint is
    # survivorship-biased (100% coverage for live coins, ~50% of delisted
    # coin-weeks), and letting it supply core fields would import that bias into
    # the universe itself. The snapshot panel stays authoritative.
    # Two sources, coalesced. CMC's per-coin endpoint is the live one; the Gandal
    # CC0 panel is a 2018/2019-vintage scrape of the same upstream that still holds
    # OHLC for coins CMC has since purged, so it fills exactly the dead-coin gap.
    # Every Gandal match was validated against this panel's own closes before being
    # admitted (see gandal_ohlc.py); 91% agree to under 0.1%.
    parts = []
    ohlc_glob = str(Path(ohlc_root) / "*.parquet")
    if Path(ohlc_root).exists() and any(Path(ohlc_root).glob("*.parquet")):
        parts.append(f"""
            SELECT coin_id, CAST(date AS DATE) AS date, high, low, 'cmc' AS hl_src
            FROM read_parquet('{ohlc_glob}', union_by_name=true)
            WHERE high IS NOT NULL AND low IS NOT NULL""")
    gp = Path(gandal_path)
    if gp.exists():
        parts.append(f"""
            SELECT coin_id, CAST(date AS DATE) AS date, high, low, 'gandal' AS hl_src
            FROM read_parquet('{gp}')
            WHERE high IS NOT NULL AND low IS NOT NULL""")

    if parts:
        # Prefer CMC where both exist; Gandal fills the rest. `qualify` keeps one
        # row per coin-day deterministically.
        con.execute(f"""
            CREATE TEMP TABLE hl AS
            SELECT coin_id, date, high, low, hl_src FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY coin_id, date
                    ORDER BY CASE hl_src WHEN 'cmc' THEN 0 ELSE 1 END) AS rn
                FROM ({' UNION ALL '.join(parts)})
            ) WHERE rn = 1
        """)
    else:
        log.warning("no OHLC layer found — the four high/low indicators will be NaN")
        con.execute("CREATE TEMP TABLE hl AS "
                    "SELECT NULL::BIGINT coin_id, NULL::DATE date, NULL::DOUBLE high, "
                    "NULL::DOUBLE low, NULL::VARCHAR hl_src WHERE false")

    con.execute("""
        CREATE TEMP TABLE daily_full AS
        SELECT d.*, h.high, h.low, h.hl_src,
               (h.high IS NOT NULL AND h.low IS NOT NULL) AS has_hl
        FROM d4 d LEFT JOIN hl h
          ON d.coin_id = h.coin_id AND CAST(d.date AS DATE) = h.date
    """)
    daily_path = out_root / "panel_daily.parquet"
    con.execute(f"COPY (SELECT * FROM daily_full ORDER BY coin_id, date) "
                f"TO '{daily_path}' (FORMAT PARQUET, COMPRESSION zstd)")
    hl_cov = con.execute(
        "SELECT avg(has_hl::INT), count(*) FROM daily_full WHERE close IS NOT NULL"
    ).fetchone()
    log.info("daily panel -> %s  (high/low on %.1f%% of %s valid coin-days)",
             daily_path, 100 * (hl_cov[0] or 0), f"{hl_cov[1]:,}")

    # --- GT-1 weekly aggregation -------------------------------------------
    wk = _liu_week_sql("date")
    con.execute(f"""
        CREATE TEMP TABLE wk_days AS
        SELECT {wk} AS week_id, date, count(*) AS n_cal
        FROM (SELECT DISTINCT date FROM daily) GROUP BY 1, 2
    """)
    con.execute(f"""
        CREATE TEMP TABLE blocklen AS
        SELECT {wk} AS week_id, count(DISTINCT date) AS block_days
        FROM (SELECT DISTINCT date FROM daily) GROUP BY 1
    """)
    # returns: prod(1+r)-1 with min_obs='all' -> a single missing day voids the
    # week (b02:285 + iMinNumObs='all'). close/mcap: last. volume: sum.
    con.execute(f"""
        CREATE TEMP TABLE weekly AS
        WITH tagged AS (
            SELECT d.*, {wk} AS week_id FROM d4 d
        ), agg AS (
            SELECT coin_id, week_id,
                   any_value(name)   AS name,
                   any_value(symbol) AS symbol,
                   any_value(slug)   AS slug,
                   max(is_stablecoin::INT)::BOOLEAN AS is_stablecoin,
                   count(ret)        AS n_ret,
                   exp(sum(ln(1 + ret))) - 1 AS weekly_return,
                   arg_max(close, date)      AS close,
                   arg_max(market_cap, date) AS market_cap,
                   sum(dollar_volume)        AS dollar_volume,
                   max(date)                 AS last_date
            FROM tagged
            WHERE ret > -1 OR ret IS NULL
            GROUP BY coin_id, week_id
        )
        SELECT a.*, bl.block_days,
               CASE WHEN a.n_ret = bl.block_days THEN a.weekly_return END AS ret_all
        FROM agg a JOIN blocklen bl USING (week_id)
    """)

    # --- WEEKLY filters: b05CreateCTREND.m:62-74 ---------------------------
    min_mcap = float(cfg.universe.min_market_cap_usd)
    min_prc = float(cfg.universe.min_price_usd)
    excl_stable = bool(cfg.universe.exclude_stablecoins)
    stable_clause = "AND NOT is_stablecoin" if excl_stable else ""
    con.execute(f"""
        CREATE TEMP TABLE panel AS
        SELECT coin_id, week_id, name, symbol, slug, is_stablecoin,
               ret_all AS weekly_return, close, market_cap, dollar_volume, last_date
        FROM weekly
        -- b05CreateCTREND.m:115 `lAvail` requires a non-NaN return alongside the
        -- other fields, so a block voided by min_obs='all' is not a valid
        -- coin-week and must not reach the estimation universe.
        WHERE ret_all IS NOT NULL
          AND market_cap IS NOT NULL AND market_cap >= {min_mcap}
          AND close IS NOT NULL AND close >= {min_prc}
          AND dollar_volume IS NOT NULL AND dollar_volume > 0
          {stable_clause}
    """)

    n_panel = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    n_coins = con.execute("SELECT count(DISTINCT coin_id) FROM panel").fetchone()[0]

    # --- point-in-time universe + delisting registry -----------------------
    con.execute("""
        CREATE TEMP TABLE registry AS
        SELECT coin_id,
               any_value(name) AS name, any_value(symbol) AS symbol,
               min(week_id) AS first_week, max(week_id) AS last_week,
               max(last_date) AS last_trade_date,
               count(*) AS n_weeks
        FROM panel GROUP BY coin_id
    """)
    sample_end = con.execute("SELECT max(week_id) FROM panel").fetchone()[0]
    con.execute(f"""
        CREATE TEMP TABLE delistings AS
        SELECT *, (last_week < {sample_end}) AS is_delisted FROM registry
    """)

    panel_path = out_root / "panel_weekly.parquet"
    reg_path = out_root / "universe_registry.parquet"
    con.execute(f"COPY (SELECT * FROM panel ORDER BY week_id, coin_id) "
                f"TO '{panel_path}' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute(f"COPY (SELECT * FROM delistings ORDER BY coin_id) "
                f"TO '{reg_path}' (FORMAT PARQUET, COMPRESSION zstd)")

    dead = con.execute("SELECT count(*) FROM delistings WHERE is_delisted").fetchone()[0]
    total = con.execute("SELECT count(*) FROM delistings").fetchone()[0]
    log.info("panel   rows=%s coins=%s -> %s", f"{n_panel:,}", f"{n_coins:,}", panel_path)
    log.info("universe coins=%s delisted=%s (%.1f%%) -> %s",
             f"{total:,}", f"{dead:,}", 100 * dead / max(total, 1), reg_path)
    con.close()
    return {"panel_rows": n_panel, "panel_coins": n_coins,
            "universe_coins": total, "delisted": dead,
            "panel_path": str(panel_path), "registry_path": str(reg_path)}


def main(argv: list[str] | None = None) -> int:
    from ctrend.config import load_config

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="configs/replication.yaml")
    p.add_argument("--raw", default=RAW_GLOB)
    p.add_argument("--out", type=Path, default=OUT_ROOT)
    p.add_argument("--ohlc", default="data/raw/cmc_ohlc")
    p.add_argument("--gandal", default="data/curated/gandal_ohlc.parquet")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    curate(load_config(a.config), a.raw, a.out, a.ohlc, a.gandal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
