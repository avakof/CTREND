"""SPEC §4.3 step 1 — weighted cross-sectional regression properties."""

import numpy as np
import pytest

from ctrend.signal.fm_wls import fm_wls


@pytest.fixture
def panel():
    rng = np.random.default_rng(11)
    N, J = 4000, 5
    z = rng.uniform(-0.5, 0.5, (N, J))
    b = np.array([1.0, -2.0, 0.0, 0.5, 3.0])
    r = z @ b + rng.normal(0, 0.01, N)
    mcap = rng.lognormal(3, 1, N)
    return z, r, mcap, b


def test_recovers_univariate_loadings_when_signals_are_near_orthogonal(panel):
    z, r, mcap, b = panel
    alpha, beta = fm_wls(z, r, mcap)
    assert beta == pytest.approx(b, abs=0.2)
    assert alpha.shape == beta.shape == (z.shape[1],)


def test_matches_an_explicit_weighted_least_squares_solve(panel):
    z, r, mcap, _ = panel
    alpha, beta = fm_wls(z, r, mcap)
    w = mcap / mcap.sum()
    for j in range(z.shape[1]):
        X = np.column_stack([np.ones(len(r)), z[:, j]])
        WX = X * w[:, None]
        coef = np.linalg.solve(X.T @ WX, WX.T @ r)
        assert coef[0] == pytest.approx(alpha[j], rel=1e-9)
        assert coef[1] == pytest.approx(beta[j], rel=1e-9)


def test_normalization_is_a_real_decision_not_a_cosmetic_one(panel):
    """Why ``wls_weights_normalize`` needs a DECISIONS row.

    With normalised weights the estimator is invariant to a rescale of market
    cap, because ``zm``/``rm`` are then genuine weighted means. Drop the
    normalisation and they are not means at all: the whole closed form changes,
    alpha and beta included. The golden normalises, so this codebase does too.
    """
    z, r, mcap, _ = panel
    a1, b1 = fm_wls(z, r, mcap)
    a2, b2 = fm_wls(z, r, mcap * 1_000_000.0)
    assert np.allclose(a1, a2, rtol=1e-9) and np.allclose(b1, b2, rtol=1e-9)

    a_raw, b_raw = fm_wls(z, r, mcap, normalize=False)
    assert not np.allclose(b_raw, b1)
    assert not np.allclose(a_raw, a1)


def test_degenerate_signal_column_is_floored_not_infinite():
    """The ``np.maximum(var, 1e-12)`` guard: a tied rank column has zero variance."""
    z = np.zeros((50, 3))
    z[:, 0] = np.linspace(-0.5, 0.5, 50)
    z[:, 1] = 0.25  # every coin tied -> zero cross-sectional variance
    z[:, 2] = np.linspace(0.5, -0.5, 50)
    r = np.linspace(-1, 1, 50)
    mcap = np.ones(50)
    alpha, beta = fm_wls(z, r, mcap, var_floor=1e-12)
    assert np.isfinite(alpha).all() and np.isfinite(beta).all()
    # the guard divides ~0 by the 1e-12 floor rather than by 0
    assert abs(beta[1]) < 1e-15, "a tied column must carry no cross-sectional slope"


def test_uniform_weights_reduce_to_ordinary_least_squares(panel):
    z, r, _, _ = panel
    alpha, beta = fm_wls(z, r, np.ones(len(r)))
    for j in range(z.shape[1]):
        s, i = np.polyfit(z[:, j], r, 1)
        assert beta[j] == pytest.approx(s, rel=1e-9)
        assert alpha[j] == pytest.approx(i, rel=1e-8)
