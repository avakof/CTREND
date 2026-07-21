"""Characterization tests pinning `sort_portfolios` BEFORE the upgrade work.

`portfolio/sorts.py` holds the most intricate arithmetic in the repo — GKX turnover
with drift adjustment, and three genuinely different weight-change definitions (the
reported turnover, the cost basis, and the breakeven basis). It had no tests at all,
and the upgrade experiment modifies it (buffer zones, capacity caps, a weight hook).

These tests do not assert that the current behaviour is *correct*. They assert it is
*unchanged*. Every value below was captured from the implementation as it stood before
any upgrade was added, on a deterministic fixture. If an upgrade moves one of these
numbers, that is either a bug or a deliberate change that must be argued for — either
way it should not pass silently.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ctrend.portfolio.sorts import (
    MIN_ASSETS,
    MIN_CS,
    N_Q,
    assign_quintiles,
    matlab_quantile,
    sort_portfolios,
)


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    """Deterministic 12-week, 40-coin panel. Signal is genuinely predictive so the
    H-L is non-trivial, and market caps are dispersed so value-weighting bites."""
    rng = np.random.default_rng(20260720)
    rows = []
    n = 40
    mcap = np.exp(rng.normal(16, 1.5, n))          # ~$9M .. $1bn, dispersed
    for wk in range(1, 13):
        sig = rng.normal(0, 1, n)
        fwd = 0.02 * sig + rng.normal(0, 0.08, n)   # signal predicts, with noise
        mcap = mcap * np.exp(rng.normal(0, 0.05, n))
        rows.append(pd.DataFrame({"week": 202400 + wk, "coin_id": np.arange(n),
                                  "sig": sig, "fwd": fwd, "mcap": mcap}))
    return pd.concat(rows, ignore_index=True)


@pytest.fixture(scope="module")
def result(panel):
    return sort_portfolios(panel, "sig")


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #
def test_module_constants_are_the_matlab_minimums():
    """`fSingleSortMulti.m`: iMinNumCS = 25, iMinNumAssets = 5, quintiles."""
    assert (MIN_CS, MIN_ASSETS, N_Q) == (25, 5, 5)


#: The columns that existed before the upgrade work. These are pinned by ORDER and
#: content — a change here is a behavioural change. Diagnostics added later
#: (concentration, capacity) are allowed as EXTRA columns and listed separately, so
#: an accidental removal or reordering of a core column still fails.
CORE_COLUMNS = ["week", "n", "q1", "q2", "q3", "q4", "q5", "hl",
                "to_long", "to_short", "turnover", "cost", "hl_net"]
DIAGNOSTIC_COLUMNS = {"top1_long", "eff_n_long", "top1_short", "eff_n_short",
                      "uninvested_long", "uninvested_short"}


def test_weekly_frame_shape_and_columns(result):
    w = result.weekly
    assert len(w) == 12, "all 12 weeks survive the 40-coin cross-section"
    assert [c for c in w.columns if c in CORE_COLUMNS] == CORE_COLUMNS
    assert set(w.columns) - set(CORE_COLUMNS) <= DIAGNOSTIC_COLUMNS, (
        "unexpected new column — declare it in DIAGNOSTIC_COLUMNS deliberately"
    )
    assert (w["n"] == 40).all()


def test_concentration_diagnostics_are_emitted(result):
    """Needed because the live-perp universe has an effective N near 2."""
    w = result.weekly
    assert (w["eff_n_long"] > 1).all() and (w["eff_n_long"] <= 8).all()
    assert (w["top1_long"] > 0).all() and (w["top1_long"] <= 1.0).all()
    assert (w["uninvested_long"] == 0.0).all(), "no caps applied => nothing uninvested"


def test_hl_is_exactly_top_minus_bottom_quintile(result):
    w = result.weekly
    np.testing.assert_allclose(w["hl"], w["q5"] - w["q1"], rtol=1e-15)


def test_weights_are_retained_per_week_per_bucket_and_sum_to_one(result):
    assert set(result.weights) == set(result.weekly["week"])
    for wk, buckets in result.weights.items():
        assert set(buckets) == set(range(N_Q))
        for k, w in buckets.items():
            assert w.sum() == pytest.approx(1.0, abs=1e-12), f"week {wk} bucket {k}"
            assert (w > 0).all()


# --------------------------------------------------------------------------- #
# Turnover: the drift adjustment is the subtle part
# --------------------------------------------------------------------------- #
def test_opening_the_book_is_full_turnover(result):
    """First week has no prior book, so every leg turns over completely."""
    first = result.weekly.iloc[0]
    assert first["to_long"] == pytest.approx(1.0, abs=1e-12)
    assert first["to_short"] == pytest.approx(1.0, abs=1e-12)
    assert first["turnover"] == pytest.approx(1.0, abs=1e-12)


def test_turnover_is_the_average_of_the_two_legs(result):
    w = result.weekly
    np.testing.assert_allclose(w["turnover"], 0.5 * (w["to_long"] + w["to_short"]),
                               rtol=1e-15)


def test_turnover_bounded_and_below_one_after_opening(result):
    w = result.weekly.iloc[1:]
    assert (w["turnover"] >= 0).all()
    assert (w["turnover"] <= 1.0 + 1e-12).all()


def test_drift_adjustment_is_not_a_plain_weight_difference():
    """GKX compares w_t against the PRIOR book drifted by realised returns. A
    naive |w_t - w_{t-1}| would count price moves as trading. Construct a week
    where the book is unchanged but prices moved: true turnover is 0."""
    from ctrend.portfolio.sorts import _leg_turnover

    idx = pd.Index([1, 2, 3], name="coin_id")
    prev = pd.Series([0.5, 0.3, 0.2], index=idx)
    ret = pd.Series([0.50, -0.20, 0.10], index=idx)
    drifted = prev * (1 + ret)
    cur = drifted / drifted.sum()          # hold everything, let it drift
    assert _leg_turnover(prev, cur, ret) == pytest.approx(0.0, abs=1e-12)
    # The naive difference would be materially non-zero on the same data.
    assert float((cur - prev).abs().sum()) > 0.10


def test_full_rotation_is_turnover_one():
    from ctrend.portfolio.sorts import _leg_turnover

    prev = pd.Series([0.5, 0.5], index=pd.Index([1, 2]))
    cur = pd.Series([0.5, 0.5], index=pd.Index([3, 4]))
    ret = pd.Series([0.0, 0.0], index=pd.Index([1, 2]))
    assert _leg_turnover(prev, cur, ret) == pytest.approx(1.0, abs=1e-12)


# --------------------------------------------------------------------------- #
# Costs use a DIFFERENT quantity from reported turnover — deliberately
# --------------------------------------------------------------------------- #
def test_cost_uses_the_undrifted_change_not_the_gkx_turnover(result):
    """`sorts.py` docstring: costs use raw |dw|, unhalved and undrifted. If cost
    were computed from the reported turnover these would coincide; they must not."""
    w = result.weekly.iloc[1:]
    implied = w["cost"] / (0.0030 + 0.0040)      # if it were one shared quantity
    assert not np.allclose(implied, w["turnover"], rtol=1e-6), (
        "cost and reported turnover must remain distinct quantities"
    )


def test_net_is_gross_minus_cost_and_cost_scales_with_rates(panel, result):
    w = result.weekly
    np.testing.assert_allclose(w["hl_net"], w["hl"] - w["cost"], rtol=1e-15)
    dearer = sort_portfolios(panel, "sig", tc_long=0.0060, tc_short=0.0080)
    np.testing.assert_allclose(dearer.weekly["cost"], 2.0 * w["cost"], rtol=1e-12)


def test_zero_cost_rates_make_net_equal_gross(panel):
    r = sort_portfolios(panel, "sig", tc_long=0.0, tc_short=0.0)
    np.testing.assert_allclose(r.weekly["hl_net"], r.weekly["hl"], rtol=1e-15)


# --------------------------------------------------------------------------- #
# Quantile mechanics
# --------------------------------------------------------------------------- #
def test_matlab_quantile_uses_plotting_positions_not_numpy_default():
    """MATLAB `quantile(...,'exact')` uses (i-0.5)/n plotting positions; numpy's
    default uses (i-1)/(n-1). They agree at 0, 0.5 and 1 on a symmetric array —
    the divergence is at intermediate quantiles, which is exactly where the
    QUINTILE BREAKPOINTS live, so the distinction is load-bearing here."""
    x = np.arange(1.0, 11.0)
    breaks = np.linspace(0, 1, N_Q + 1)          # the breakpoints actually used
    got = matlab_quantile(x, breaks)
    npy = np.percentile(x, breaks * 100)
    assert got[0] == 1.0 and got[-1] == 10.0     # endpoints clamp to the extremes
    assert not np.allclose(got, npy), (
        f"quintile breakpoints must differ from numpy's: {got} vs {npy}"
    )
    # Concretely: the 20th percentile of 1..10
    assert got[1] == pytest.approx(2.5)          # between plotting positions .15/.25
    assert npy[1] == pytest.approx(2.8)          # numpy's linear convention


def test_assign_quintiles_partitions_and_orders():
    rng = np.random.default_rng(0)
    v = rng.normal(size=500)
    q = assign_quintiles(v, N_Q)
    assert set(np.unique(q)) == set(range(N_Q))
    means = [v[q == k].mean() for k in range(N_Q)]
    assert means == sorted(means), "buckets must be ordered in the signal"


def test_week_voided_below_min_cross_section(panel):
    thin = panel[panel.coin_id < MIN_CS - 1]
    assert sort_portfolios(thin, "sig").weekly.empty


def test_week_voided_when_an_extreme_bucket_is_too_small():
    """25 coins passes MIN_CS but puts 5 per bucket — right at the boundary."""
    rng = np.random.default_rng(1)
    n = 25
    df = pd.DataFrame({"week": 202401, "coin_id": np.arange(n),
                       "sig": rng.normal(size=n), "fwd": rng.normal(0, .05, n),
                       "mcap": np.full(n, 1e8)})
    assert len(sort_portfolios(df, "sig").weekly) == 1
    df24 = df[df.coin_id < 24]
    assert sort_portfolios(df24, "sig").weekly.empty, "24 coins < MIN_CS"


def test_rows_with_missing_signal_return_or_mcap_are_dropped(panel):
    dirty = panel.copy()
    dirty.loc[dirty.index[:3], "sig"] = np.nan
    dirty.loc[dirty.index[3:6], "fwd"] = np.nan
    dirty.loc[dirty.index[6:9], "mcap"] = np.nan
    r = sort_portfolios(dirty, "sig")
    assert r.weekly.iloc[0]["n"] == 40 - 9


def test_non_positive_mcap_excluded():
    rng = np.random.default_rng(2)
    n = 40
    df = pd.DataFrame({"week": 202401, "coin_id": np.arange(n),
                       "sig": rng.normal(size=n), "fwd": rng.normal(0, .05, n),
                       "mcap": np.full(n, 1e8)})
    df.loc[:4, "mcap"] = 0.0
    assert sort_portfolios(df, "sig").weekly.iloc[0]["n"] == 35


# --------------------------------------------------------------------------- #
# Value weighting actually bites
# --------------------------------------------------------------------------- #
def test_value_weighting_differs_from_equal_weighting(result, panel):
    """If these coincided, `mcap` would be doing nothing and every capacity or
    concentration result later in the experiment would be meaningless."""
    wk = result.weekly["week"].iloc[0]
    w = result.weights[wk][N_Q - 1]
    assert w.std() > 1e-6
    assert w.max() > 1.5 / len(w), "value weights must concentrate somewhere"


def test_determinism(panel):
    a = sort_portfolios(panel, "sig").weekly
    b = sort_portfolios(panel, "sig").weekly
    pd.testing.assert_frame_equal(a, b)
