"""Integrity guards for the OHLC backfill.

Both tests exist because of bugs that produced *plausible* data rather than errors:

1. The CMC endpoint fits a ~732-point cap by widening the sampling interval instead
   of truncating. A multi-year request silently returned 6-day bars. Fed into a
   14-day stochastic that yields a number, not an exception.
2. Chunked fetching turns a throttled window into a hole in the middle of an
   otherwise-complete series, which would corrupt every rolling window spanning it.

Neither failure is visible downstream, so both are pinned here.
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd
import pytest

from ctrend.ingest.cmc_ohlc import CHUNK_DAYS, MAX_POINTS, _WindowFailed, fetch_coin

OHLC_GLOB = "data/raw/cmc_ohlc/*.parquet"


def test_chunk_size_stays_below_the_endpoint_cap():
    """The whole defence against silent down-sampling is this inequality."""
    assert CHUNK_DAYS < MAX_POINTS, "a chunk wider than the cap is silently resampled"
    assert CHUNK_DAYS >= 300, "needlessly small chunks multiply the request count"


def test_a_failed_window_aborts_the_coin_rather_than_leaving_a_hole(monkeypatch):
    """A partial series must never be returned as if it were complete."""
    import ctrend.ingest.cmc_ohlc as mod

    calls = {"n": 0}

    def flaky(coin_id, t0, t1, *, delay, retries=3):
        calls["n"] += 1
        if calls["n"] == 2:                      # second chunk is throttled
            raise _WindowFailed(coin_id)
        return [{"coin_id": coin_id, "date": pd.Timestamp("2016-01-01"),
                 "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
                 "volume_ohlc": 10.0, "market_cap_ohlc": 100.0}]

    monkeypatch.setattr(mod, "_fetch_window", flaky)
    t0 = int(pd.Timestamp("2015-01-01").timestamp())
    t1 = int(pd.Timestamp("2018-01-01").timestamp())
    with pytest.raises(_WindowFailed):
        fetch_coin(1, t0, t1, delay=0.0)


@pytest.mark.skipif(not glob.glob(OHLC_GLOB), reason="OHLC layer not harvested yet")
def test_harvested_series_are_daily_not_downsampled():
    """The regression guard: real files must have 1-day spacing.

    A 6-day-spaced series would still populate every indicator column, so nothing
    downstream would complain. This is the only place the corruption is visible.
    """
    files = sorted(glob.glob(OHLC_GLOB))
    checked = 0
    for f in files[:400]:
        d = pd.read_parquet(f, columns=["date"])
        if len(d) < 30:
            continue
        gaps = d["date"].sort_values().diff().dt.days.dropna()
        median_gap = float(np.median(gaps))
        assert median_gap == 1.0, (
            f"{f}: median gap {median_gap}d — the endpoint down-sampled this series; "
            "CHUNK_DAYS must stay under the point cap"
        )
        checked += 1
    assert checked > 0, "no series long enough to check spacing"


@pytest.mark.skipif(not glob.glob(OHLC_GLOB), reason="OHLC layer not harvested yet")
def test_high_low_bracket_the_close_where_present():
    """Cheap sanity check on the joined columns: low <= close <= high."""
    for f in sorted(glob.glob(OHLC_GLOB))[:200]:
        d = pd.read_parquet(f)
        if d.empty:
            continue
        ok = d[["high", "low", "close"]].notna().all(axis=1)
        if not ok.any():
            continue
        s = d[ok]
        assert (s["low"] <= s["high"] + 1e-12).all(), f"{f}: low > high"
        assert (s["close"] >= s["low"] - 1e-9).all(), f"{f}: close below low"
        assert (s["close"] <= s["high"] + 1e-9).all(), f"{f}: close above high"
