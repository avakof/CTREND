"""Upgrade mechanics: every new capability must have a BIT-EXACT identity default.

That is the property which lets six upgrades land on a codebase whose tests pin an
exact lambda to 1e-12 and an exact selection set. If `buffer_width=0`, `halflife=0`,
`max_name_weight=1.0` or `participation=None` changed a single number, the whole
experiment would be built on a moved baseline without anyone noticing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ctrend.portfolio.overlays import beta_hedge, ewma_signal, vol_target
from ctrend.portfolio.sorts import cap_weights, sort_portfolios


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    rng = np.random.default_rng(20260720)
    rows, n = [], 40
    mcap = np.exp(rng.normal(16, 1.5, n))
    for wk in range(1, 21):
        sig = rng.normal(0, 1, n)
        fwd = 0.02 * sig + rng.normal(0, 0.08, n)
        mcap = mcap * np.exp(rng.normal(0, 0.05, n))
        rows.append(pd.DataFrame({"week": 202400 + wk, "coin_id": np.arange(n),
                                  "sig": sig, "fwd": fwd, "mcap": mcap,
                                  "dvol": mcap * rng.uniform(0.01, 0.2, n)}))
    return pd.concat(rows, ignore_index=True)


# --------------------------------------------------------------------------- #
# Identity defaults — the load-bearing property
# --------------------------------------------------------------------------- #
def test_buffer_zero_is_bit_exact_identity(panel):
    a = sort_portfolios(panel, "sig")
    b = sort_portfolios(panel, "sig", buffer_width=0.0)
    pd.testing.assert_frame_equal(a.weekly, b.weekly)


def test_name_cap_of_one_is_bit_exact_identity(panel):
    a = sort_portfolios(panel, "sig")
    b = sort_portfolios(panel, "sig", max_name_weight=1.0)
    pd.testing.assert_frame_equal(a.weekly, b.weekly)


def test_no_capacity_args_is_bit_exact_identity(panel):
    a = sort_portfolios(panel, "sig")
    b = sort_portfolios(panel, "sig", adv_col="dvol")  # no book size => inactive
    pd.testing.assert_frame_equal(a.weekly, b.weekly)


def test_ewma_halflife_zero_is_identity():
    d = pd.DataFrame({"week": [1, 2, 3] * 2, "coin_id": [1] * 3 + [2] * 3,
                      "ctrend": [0.1, 0.2, 0.3, -0.1, 0.0, 0.1]})
    pd.testing.assert_frame_equal(ewma_signal(d, halflife_weeks=0.0), d.copy())


# --------------------------------------------------------------------------- #
# U3 buffering
# --------------------------------------------------------------------------- #
def test_buffer_reduces_turnover(panel):
    base = sort_portfolios(panel, "sig").weekly["turnover"].mean()
    for width in (0.05, 0.10, 0.15):
        buf = sort_portfolios(panel, "sig", buffer_width=width).weekly["turnover"].mean()
        assert buf <= base + 1e-12, f"buffer {width} raised turnover"


def test_buffer_still_respects_min_assets(panel):
    r = sort_portfolios(panel, "sig", buffer_width=0.15)
    assert not r.weekly.empty
    for _, buckets in r.weights.items():
        assert len(buckets[0]) >= 5 and len(buckets[4]) >= 5


def test_ewma_is_causal():
    """A future score must not alter a past smoothed value."""
    d = pd.DataFrame({"week": [1, 2, 3, 4], "coin_id": 1,
                      "ctrend": [0.1, 0.2, 0.3, 0.4]})
    a = ewma_signal(d, halflife_weeks=2)
    d2 = d.copy()
    d2.loc[3, "ctrend"] = 99.0
    b = ewma_signal(d2, halflife_weeks=2)
    np.testing.assert_allclose(a["ctrend"][:3], b["ctrend"][:3], rtol=1e-12)


def test_ewma_does_not_carry_a_stale_score_across_a_gap_at_full_weight():
    """Coin present at weeks 1 and 12 only: the dense-axis reindex must decay the
    old value over the gap rather than treating it as last week's."""
    d = pd.DataFrame({"week": [1, 12], "coin_id": [1, 1], "ctrend": [1.0, 0.0]})
    d = pd.concat([d, pd.DataFrame({"week": range(1, 13), "coin_id": 2,
                                    "ctrend": 0.0})], ignore_index=True)
    out = ewma_signal(d, halflife_weeks=1.0)
    late = float(out[(out.coin_id == 1) & (out.week == 12)]["ctrend"].iloc[0])
    assert abs(late) < 0.05, f"stale score survived the gap: {late}"


# --------------------------------------------------------------------------- #
# U6 capacity / concentration
# --------------------------------------------------------------------------- #
def test_name_cap_binds_and_leaves_cash():
    w = pd.Series([0.7, 0.2, 0.1], index=[1, 2, 3])
    capped, un = cap_weights(w, max_name_weight=0.10)
    assert capped.max() <= 0.10 + 1e-12
    assert capped.sum() + un == pytest.approx(1.0, abs=1e-12)
    assert un > 0, "a binding cap with no headroom must leave cash"


def test_renormalize_differs_from_cash_when_the_cap_binds():
    """If these agreed, `renormalize` would not be assuming away the constraint."""
    w = pd.Series([0.7, 0.2, 0.1], index=[1, 2, 3])
    cash, un_c = cap_weights(w, max_name_weight=0.10, residual="cash")
    renm, un_r = cap_weights(w, max_name_weight=0.10, residual="renormalize")
    assert un_c > 0 and un_r == 0.0
    assert renm.sum() == pytest.approx(1.0, abs=1e-12)
    assert not np.allclose(cash.to_numpy(), renm.to_numpy())


def test_cap_is_idempotent():
    w = pd.Series([0.6, 0.25, 0.15], index=[1, 2, 3])
    once, _ = cap_weights(w, max_name_weight=0.30)
    twice, _ = cap_weights(once, max_name_weight=0.30)
    np.testing.assert_allclose(once.to_numpy(), twice.to_numpy(), rtol=1e-12)


def test_name_cap_reduces_concentration_in_the_sort(panel):
    base = sort_portfolios(panel, "sig").weekly
    capped = sort_portfolios(panel, "sig", max_name_weight=0.10).weekly
    assert capped["top1_long"].mean() < base["top1_long"].mean()
    assert capped["eff_n_long"].mean() > base["eff_n_long"].mean()


def test_adv_cap_leaves_cash_when_book_is_large(panel):
    r = sort_portfolios(panel, "sig", adv_col="dvol",
                        book_size_usd=1e12, participation=0.01)
    assert r.weekly["uninvested_long"].mean() > 0, "a $1tn book must not fit"


# --------------------------------------------------------------------------- #
# U2 volatility targeting
# --------------------------------------------------------------------------- #
def _wk(n=60, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"week": np.arange(202401, 202401 + n),
                         "hl": rng.normal(0.005, 0.05, n),
                         "turnover": np.full(n, 0.7)})


def test_vol_target_leverage_uses_only_past_returns():
    """The `.shift(1)`. Perturbing week t must not change k_t."""
    d = _wk()
    a = vol_target(d, target_ann_vol=0.20)
    d2 = d.copy()
    d2.loc[40, "hl"] = 5.0
    b = vol_target(d2, target_ann_vol=0.20)
    np.testing.assert_allclose(a["k"][: 41], b["k"][: 41], rtol=1e-12)


def test_vol_target_clips_leverage():
    d = _wk()
    out = vol_target(d, target_ann_vol=5.0, max_leverage=1.5)
    assert out["k"].max() <= 1.5 + 1e-12


def test_vol_target_cost_includes_the_leverage_rebalancing_term():
    """Without the |k_t - k_{t-1}| term, vol targeting looks free."""
    d = _wk()
    out = vol_target(d, target_ann_vol=0.20, tc=0.005)
    naive = 0.005 * (out["k"] * out["turnover"])
    assert (out["cost_vt"] >= naive - 1e-12).all()
    assert out["cost_vt"].sum() > naive.sum(), "leverage rebalancing must cost something"


# --------------------------------------------------------------------------- #
# U4 beta hedge
# --------------------------------------------------------------------------- #
def test_beta_is_causal():
    rng = np.random.default_rng(1)
    n = 80
    bench = rng.normal(0, 0.05, n)
    d = pd.DataFrame({"week": np.arange(202401, 202401 + n),
                      "hl": 0.8 * bench + rng.normal(0, 0.01, n), "mkt": bench})
    a = beta_hedge(d, ret_col="hl", bench_col="mkt", window_weeks=26)
    d2 = d.copy()
    d2.loc[60, "hl"] = 9.0
    b = beta_hedge(d2, ret_col="hl", bench_col="mkt", window_weeks=26)
    np.testing.assert_allclose(a["beta"][: 61], b["beta"][: 61], rtol=1e-12)


def test_hedging_a_pure_beta_series_removes_most_variance():
    rng = np.random.default_rng(2)
    n = 120
    bench = rng.normal(0, 0.05, n)
    d = pd.DataFrame({"week": np.arange(202401, 202401 + n),
                      "hl": 1.0 * bench, "mkt": bench})
    out = beta_hedge(d, ret_col="hl", bench_col="mkt", window_weeks=26)
    tail = out.iloc[30:]
    assert tail["hl_hedged"].std() < 0.2 * tail["hl"].std()


def test_funding_credit_is_optional_and_signed_toward_the_short():
    """A short perp RECEIVES positive funding. Crediting it must HELP the hedge;
    if this test inverts, a cost has silently become a subsidy."""
    n = 80
    rng = np.random.default_rng(3)
    bench = rng.normal(0, 0.05, n)
    weeks = np.arange(202401, 202401 + n)
    d = pd.DataFrame({"week": weeks, "hl": 0.8 * bench + 0.001, "mkt": bench})
    fund = pd.Series(0.002, index=weeks)          # persistently positive funding
    on = beta_hedge(d, ret_col="hl", bench_col="mkt", funding=fund, credit_funding=True)
    off = beta_hedge(d, ret_col="hl", bench_col="mkt", funding=fund, credit_funding=False)
    assert on["hl_hedged"].mean() > off["hl_hedged"].mean()
    assert (off["funding_pnl"] == 0).all()
