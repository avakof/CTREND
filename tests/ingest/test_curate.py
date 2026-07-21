"""Curation pipeline — the DAILY filters, the cascade, and GT-1 weekly blocks.

Each test targets a step whose ordering is load-bearing: doing the truncation
weekly instead of daily, or skipping the cascade, silently changes the universe
rather than raising.
"""
from __future__ import annotations

from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd
import pytest

from ctrend.ingest.curate import _liu_week_sql, curate


def _write_raw(root, frames: list[pd.DataFrame]) -> str:
    d = root / "raw"
    d.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_parquet(d / "all.parquet", index=False)
    return str(d / "*.parquet")


def _coin(coin_id, dates, price, mcap, vol, *, stable=False, name=None):
    n = len(dates)
    return pd.DataFrame({
        "id": coin_id, "name": name or f"C{coin_id}", "symbol": f"S{coin_id}",
        "slug": f"c{coin_id}", "cmcRank": 1.0, "circulatingSupply": 1.0,
        "totalSupply": 1.0, "maxSupply": 1.0, "dateAdded": "2013-01-01",
        "price": np.asarray(price, dtype=float),
        "marketCap": np.asarray(mcap, dtype=float),
        "volume24h": np.asarray(vol, dtype=float),
        "is_stablecoin": stable, "tags": "", "date": pd.to_datetime(dates),
    })


# --------------------------------------------------------------------------- #
# GT-1 — the Liu year-block calendar, expressed in SQL
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "day,expect",
    [("2015-01-01", 201501), ("2015-01-07", 201501), ("2015-01-08", 201502),
     ("2015-12-24", 201552), ("2015-12-31", 201552),   # wk52 absorbs the tail
     ("2016-12-31", 201652), ("2016-01-01", 201601)],  # leap year: 9-day wk52
)
def test_liu_week_sql_matches_the_block_definition(day, expect):
    con = duckdb.connect()
    got = con.execute(
        f"SELECT {_liu_week_sql('d')} FROM (SELECT DATE '{day}' AS d)"
    ).fetchone()[0]
    assert got == expect


def test_every_year_has_exactly_52_blocks():
    con = duckdb.connect()
    n = con.execute(f"""
        SELECT count(DISTINCT {_liu_week_sql('d')})
        FROM (SELECT unnest(generate_series(DATE '2016-01-01', DATE '2016-12-31',
                                            INTERVAL 1 DAY)) AS d)
    """).fetchone()[0]
    assert n == 52, "week 52 must absorb the remainder, not spill into a 53rd"


# --------------------------------------------------------------------------- #
# DAILY filters and the cascade
# --------------------------------------------------------------------------- #
@pytest.fixture
def cfg_corrected(replication_cfg):
    """`corrected` isolates the truncation cascade from the first-obs quirk."""
    return replace(replication_cfg,
                   returns=replace(replication_cfg.returns, first_obs_quirk="corrected"))


def test_mcap_above_bitcoin_and_non_positive_are_dropped(tmp_path, cfg_corrected):
    dates = pd.date_range("2015-01-01", periods=14)
    frames = [
        _coin(1, dates, 100.0, 1e9, 1e6),            # BTC
        _coin(2, dates, 10.0, 5e9, 1e6),             # mcap > BTC -> dropped
        _coin(3, dates, 10.0, 0.0, 1e6),             # mcap <= 0  -> dropped
        _coin(4, dates, 10.0, 1e8, 1e6),             # fine
    ]
    out = curate(cfg_corrected, _write_raw(tmp_path, frames), tmp_path / "cur")
    panel = pd.read_parquet(out["panel_path"])
    assert set(panel.coin_id) == {1, 4}, "b01ReadData.m:59-62 screens are daily"


def test_truncation_is_per_day_cross_sectional_and_drops(tmp_path, cfg_corrected):
    """GT-2: outliers become NaN, and the cascade wipes that coin-day entirely.

    A coin-day whose return is truncated must lose its market cap and volume too
    (b02:76-81 + fEnsureAllObs), which in turn voids the whole week because weekly
    returns need every day present.
    """
    dates = pd.date_range("2015-01-01", periods=14)
    n = len(dates)
    frames = [_coin(1, dates, [100.0] * n, [1e12] * n, [1e6] * n)]
    # The 0.5/99.5 cut only removes anything once the daily cross-section is
    # large enough for 0.5% to be a whole observation, i.e. N >= 200. With the
    # 42-coin panel this test originally used, the 99.5th percentile IS the
    # maximum and nothing is truncated -- a real property of the rule, not a bug.
    rng = np.random.default_rng(0)
    for cid in range(2, 302):
        px = 10.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
        frames.append(_coin(cid, dates, px, np.full(n, 1e8), np.full(n, 1e6)))
    # One coin with an extreme move on a single day, well inside the sample.
    spike = 10.0 * np.ones(n)
    spike[8] = 10_000.0
    frames.append(_coin(999, dates, spike, np.full(n, 1e8), np.full(n, 1e6)))

    out = curate(cfg_corrected, _write_raw(tmp_path, frames), tmp_path / "cur")
    panel = pd.read_parquet(out["panel_path"])
    # The spike lands in week 2; the cascade must void that coin-week entirely.
    wk2 = panel[panel.week_id == 201502]
    assert 999 not in set(wk2.coin_id), (
        "a truncated coin-day must cascade and void the week, not be clipped"
    )
    assert len(wk2) > 100, "the ordinary cross-section must survive"


def test_weekly_return_requires_every_day_in_the_block(tmp_path, cfg_corrected):
    """b02: returns aggregate with iMinNumObs='all'."""
    dates = pd.date_range("2015-01-01", periods=14)
    gappy = list(dates[:5]) + list(dates[6:])        # 2015-01-06 missing
    frames = [
        _coin(1, dates, 100.0, 1e12, 1e6),
        _coin(2, dates, 10.0, 1e8, 1e6),             # complete
        _coin(3, gappy, 10.0, 1e8, 1e6),             # week 1 incomplete
    ]
    out = curate(cfg_corrected, _write_raw(tmp_path, frames), tmp_path / "cur")
    panel = pd.read_parquet(out["panel_path"])
    # Week 1 of the sample is void for EVERY coin: its first day has no prior
    # close, so the return is NaN and min_obs='all' voids the block. The gap in
    # coin 3 falls in week 1 too, so compare week 2, where coin 3 is complete
    # again and must reappear -- proving the rule is per-week, not per-coin.
    assert set(panel[panel.week_id == 201501].coin_id) == set(), (
        "the sample's first week has no prior close and must be void for all"
    )
    wk2 = panel[panel.week_id == 201502]
    assert {2, 3} <= set(wk2.coin_id)

    # Now put the gap inside week 2 and confirm that week alone is voided.
    gap2 = list(dates[:9]) + list(dates[10:])       # 2015-01-10 missing (week 2)
    frames2 = [_coin(1, dates, 100.0, 1e12, 1e6),
               _coin(2, dates, 10.0, 1e8, 1e6),
               _coin(3, gap2, 10.0, 1e8, 1e6)]
    out2 = curate(cfg_corrected, _write_raw(tmp_path / "b", frames2), tmp_path / "cur2")
    p2 = pd.read_parquet(out2["panel_path"])
    w2 = p2[p2.week_id == 201502]
    assert 2 in set(w2.coin_id)
    assert 3 not in set(w2.coin_id), "one missing day must void that coin-week"


def test_first_obs_quirk_is_unreachable_at_weekly_granularity(tmp_path, replication_cfg):
    """GT-2b turns out NOT to affect the weekly panel — asserted, not assumed.

    MATLAB's `NaN ~= NaN` makes `lChanged` at `b02:76` fire on already-NaN cells,
    so every coin loses its first observation. We reproduce that on the daily
    panel. But it cannot propagate: a coin's first day has a NULL return by
    construction, so the block containing it already fails `min_obs='all'` and is
    voided in BOTH modes.

    The practical consequence is worth stating plainly — this quirk costs us
    nothing in replication fidelity, and the two settings are interchangeable for
    anything downstream of weekly aggregation. Recorded in DECISIONS.md. The test
    is kept as a ratchet: if a future change makes the modes diverge weekly, that
    is a real behavioural change and should be noticed here rather than inferred
    from a moved number.
    """
    dates = pd.date_range("2015-01-01", periods=21)
    frames = [_coin(1, dates, 100.0, 1e12, 1e6)]
    for cid in range(2, 12):
        frames.append(_coin(cid, dates, 10.0 + cid, np.full(len(dates), 1e8),
                            np.full(len(dates), 1e6)))
    raw = _write_raw(tmp_path, frames)

    faithful = curate(replace(replication_cfg,
                              returns=replace(replication_cfg.returns,
                                              first_obs_quirk="faithful")),
                      raw, tmp_path / "f")
    corrected = curate(replace(replication_cfg,
                               returns=replace(replication_cfg.returns,
                                               first_obs_quirk="corrected")),
                       raw, tmp_path / "c")
    assert faithful["panel_rows"] == corrected["panel_rows"], (
        "the quirk became reachable at weekly granularity — this is a real "
        "behavioural change; re-examine GT-2b before accepting any number"
    )


def test_stablecoins_are_excluded_and_the_flag_bites(tmp_path, replication_cfg):
    dates = pd.date_range("2015-01-01", periods=14)
    frames = [
        _coin(1, dates, 100.0, 1e12, 1e6),
        _coin(2, dates, 10.0, 1e8, 1e6),
        _coin(7, dates, 1.0, 1e8, 1e6, stable=True, name="Tether"),
    ]
    raw = _write_raw(tmp_path, frames)
    on = curate(replication_cfg, raw, tmp_path / "on")
    off = curate(replace(replication_cfg,
                         universe=replace(replication_cfg.universe,
                                          exclude_stablecoins=False)),
                 raw, tmp_path / "off")
    assert 7 not in set(pd.read_parquet(on["panel_path"]).coin_id)
    assert 7 in set(pd.read_parquet(off["panel_path"]).coin_id)


def test_min_market_cap_floor_is_applied_weekly(tmp_path, cfg_corrected):
    dates = pd.date_range("2015-01-01", periods=14)
    frames = [
        _coin(1, dates, 100.0, 1e12, 1e6),
        _coin(2, dates, 10.0, 5e5, 1e6),   # below the USD 1M floor
        _coin(3, dates, 10.0, 5e6, 1e6),
    ]
    out = curate(cfg_corrected, _write_raw(tmp_path, frames), tmp_path / "cur")
    panel = pd.read_parquet(out["panel_path"])
    assert 2 not in set(panel.coin_id) and 3 in set(panel.coin_id)


# --------------------------------------------------------------------------- #
# Point-in-time universe / delisting registry (SPEC §4.1)
# --------------------------------------------------------------------------- #
def test_delisting_registry_marks_coins_that_stop_trading(tmp_path, cfg_corrected):
    dates = pd.date_range("2015-01-01", periods=35)
    frames = [
        _coin(1, dates, 100.0, 1e12, 1e6),
        _coin(2, dates, 10.0, 1e8, 1e6),                  # survives
        _coin(3, dates[:14], 10.0, 1e8, 1e6),             # dies early
    ]
    out = curate(cfg_corrected, _write_raw(tmp_path, frames), tmp_path / "cur")
    reg = pd.read_parquet(out["registry_path"]).set_index("coin_id")
    assert bool(reg.loc[3, "is_delisted"]), "dead coins must be retained AND flagged"
    assert not bool(reg.loc[2, "is_delisted"])
    assert reg.loc[3, "last_week"] < reg.loc[2, "last_week"]
    assert 3 in reg.index, "the registry must keep dead coins, not drop them (I1/§4.1)"
