"""Cross-sectional rank map to [-0.5, +0.5] (SPEC §4.2, `fCrossSectTransChars.m:48-50`).

The map is `tiedrank` -> `(r-1)/(max-1)` -> `-0.5`. Two consequences matter
downstream and are pinned here: the range is exactly [-0.5, +0.5], and the result is
mean-zero by construction — which is *why* GT-11's "forecasts are never demeaned" is
consistent rather than an oversight.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ctrend.indicators.pipeline import _liu_week, rank_map


def _wk(vals, week=201601):
    return pd.DataFrame({"week_id": week, "coin_id": range(len(vals)), "x": vals})


def test_range_is_exactly_minus_half_to_plus_half():
    out = rank_map(_wk([1.0, 2, 3, 4, 5]), ["x"])
    assert out["x"].min() == pytest.approx(-0.5)
    assert out["x"].max() == pytest.approx(0.5)


def test_map_is_monotone_in_the_underlying_value():
    vals = [5.0, 1, 3, 9, 2]
    out = rank_map(_wk(vals), ["x"])["x"].to_numpy()
    assert np.array_equal(np.argsort(vals), np.argsort(out))


def test_ranks_are_mean_zero_which_is_why_forecasts_need_no_demeaning():
    """GT-11 relies on this: the regressors are already centred."""
    rng = np.random.default_rng(0)
    out = rank_map(_wk(rng.normal(size=101)), ["x"])
    assert float(out["x"].mean()) == pytest.approx(0.0, abs=1e-12)


def test_ties_receive_the_average_rank():
    out = rank_map(_wk([1.0, 1.0, 2.0, 3.0]), ["x"])["x"].to_numpy()
    assert out[0] == pytest.approx(out[1]), "tied inputs must map identically"
    assert out[0] < out[2] < out[3]


def test_each_week_is_ranked_independently():
    df = pd.concat([_wk([1.0, 2, 3], 201601), _wk([100.0, 200, 300], 201602)])
    out = rank_map(df, ["x"])
    for w in (201601, 201602):
        s = out[out.week_id == w]["x"]
        assert s.min() == pytest.approx(-0.5) and s.max() == pytest.approx(0.5)


def test_nan_inputs_stay_nan_and_do_not_consume_a_rank():
    out = rank_map(_wk([1.0, np.nan, 2.0, 3.0]), ["x"])["x"]
    assert np.isnan(out.iloc[1])
    live = out.dropna()
    assert live.min() == pytest.approx(-0.5) and live.max() == pytest.approx(0.5)


def test_degenerate_cross_section_does_not_divide_by_zero():
    """A single-coin week (max rank == 1) would otherwise produce inf."""
    out = rank_map(_wk([7.0]), ["x"])["x"]
    assert np.isfinite(out.iloc[0]) and out.iloc[0] == pytest.approx(0.0)


def test_constant_cross_section_maps_to_the_midpoint():
    out = rank_map(_wk([3.0, 3.0, 3.0]), ["x"])["x"]
    assert np.isfinite(out).all()
    assert out.nunique() == 1


# --- GT-1 week ids, as used by the resampler -------------------------------
@pytest.mark.parametrize(
    "day,expect",
    [("2015-01-01", 201501), ("2015-01-07", 201501), ("2015-01-08", 201502),
     ("2015-12-31", 201552), ("2016-12-31", 201652)],
)
def test_liu_week_id(day, expect):
    got = _liu_week(pd.Series([pd.Timestamp(day)]))
    assert int(got.iloc[0]) == expect


def test_week_52_absorbs_the_year_end_rather_than_creating_a_53rd():
    days = pd.Series(pd.date_range("2016-01-01", "2016-12-31"))
    ids = _liu_week(days)
    assert ids.max() == 201652
    assert (ids == 201652).sum() >= 8, "week 52 runs 8-9 days"
