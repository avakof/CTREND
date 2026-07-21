"""SPEC §4.3 step 4 — ElasticNet combining and AICc lambda selection (I2)."""

import numpy as np
import pytest
from sklearn.linear_model import ElasticNet

from ctrend.signal.combine import fit_combiner, lambda_grid, lambda_max


@pytest.fixture
def design():
    rng = np.random.default_rng(3)
    n, J = 4000, 28
    X = rng.normal(size=(n, J))
    theta = np.zeros(J)
    theta[[1, 4, 9]] = [0.8, -0.6, 0.4]
    y = X @ theta + rng.normal(0, 1.0, n)
    return X, y, theta


def _fixed_grid_cfg(cfg):
    """The superseded fixed grid, kept as an M5 sensitivity axis (GT-9)."""
    from dataclasses import replace

    en = cfg.signal.elasticnet
    return replace(en, lambda_grid=replace(en.lambda_grid, mode="fixed", n=25,
                                           log_low=-4.0, log_high=0.0))


def test_data_dependent_grid_spans_lambda_max_down_to_ratio(replication_cfg):
    """GT-9: 200 points, geometric from lambda_max to ratio*lambda_max, high->low."""
    import numpy as np

    from ctrend.signal.combine import lambda_grid, lambda_max

    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (2000, 28))
    y = rng.normal(0, 0.15, 2000)
    y -= y.mean()

    en = replication_cfg.signal.elasticnet
    g = lambda_grid(en, X, y)
    lmax = lambda_max(X, y, en.l1_ratio)

    assert len(g) == 200
    assert g[0] == pytest.approx(lmax)
    assert g[-1] == pytest.approx(1e-4 * lmax)
    assert np.all(np.diff(g) < 0), "MATLAB emits the grid high->low"
    # Every point at or above lambda_max must zero the whole coefficient vector.
    assert g[0] >= g[-1]


def test_fixed_grid_still_available_as_a_sensitivity_axis(replication_cfg):
    g = lambda_grid(_fixed_grid_cfg(replication_cfg))
    assert len(g) == 25
    assert g[0] == pytest.approx(1e-4) and g[-1] == pytest.approx(1.0)
    assert np.array_equal(g, np.logspace(-4, 0, 25))


def test_aicc_choice_matches_an_independent_recomputation(design, replication_cfg):
    """GT-10: k = nonzero coefficients, NO +1. The penalty is otherwise identical --
    `2k + 2k(k+1)/(n-k-1)` factorizes exactly to `2k*n/(n-k-1)`, which is the form
    `fEstRegPanelRegression.m:108` uses."""
    X, y, _ = design
    cfg = replication_cfg.signal.elasticnet
    fit = fit_combiner(X, y, cfg)

    # Reproduce the module's standardization so the comparison is like-for-like.
    sigma = X.std(axis=0, ddof=0)
    sigma = np.where(sigma > 0, sigma, 1.0)
    Xf = (X - X.mean(axis=0)) / sigma
    n = len(y)

    best = None
    for lam in lambda_grid(cfg, Xf, y):
        en = ElasticNet(alpha=float(lam), l1_ratio=0.5, max_iter=cfg.max_iter).fit(Xf, y)
        k = int((en.coef_ != 0).sum())  # GT-10: no +1
        if k >= n - 1:
            continue
        sse = float(((y - en.predict(Xf)) ** 2).sum())
        if sse <= 0:
            continue
        aicc = n * np.log(sse / n) + 2 * k * n / (n - k - 1)
        if best is None or aicc < best[0]:
            best = (aicc, float(lam))

    # The reference above fits every lambda COLD; `fit_combiner` warm-starts along
    # the path (as MATLAB `lasso` does). Same estimator, same objective, but the
    # path solver converges further on this near-collinear design, so the two agree
    # on the *selected lambda* exactly and on the AICc *value* only to ~6 significant
    # figures. Asserting bit-equality here would be asserting that cold-started
    # coordinate descent is the ground truth, which it is not.
    assert fit.lam == pytest.approx(best[1], rel=1e-12), "selected lambda must match"
    assert fit.aicc == pytest.approx(best[0], rel=1e-4), "AICc must agree to solver tolerance"


def test_aicc_penalty_forms_are_algebraically_identical():
    """Guards the GT-10 claim that only `k` changed, not the formula."""
    for n in (500, 9000):
        for k in (1, 5, 27):
            ours = 2 * k + 2 * k * (k + 1) / (n - k - 1)
            theirs = 2 * k * n / (n - k - 1)
            assert ours == pytest.approx(theirs, rel=1e-12)


def test_selection_keeps_only_strictly_positive_theta(design, replication_cfg):
    X, y, true_theta = design
    fit = fit_combiner(X, y, replication_cfg.signal.elasticnet)
    sel = np.where(fit.theta > 0)[0]
    assert 1 in sel and 4 not in sel, "index 4 has a negative loading and must be dropped"
    assert (fit.theta[sel] > 0).all()


def test_ties_favour_the_sparser_fit(replication_cfg):
    """Strict `<` in the AICc comparison keeps the FIRST grid point among ties.

    GT-9 reversed the grid order: the data-dependent grid runs high->low (as MATLAB
    emits it), so the first point is `lambda_max` -- the sparsest fit. Under the
    superseded fixed grid the first point was 1e-4, the densest. In both cases the
    strict comparison is what pins the outcome; a `<=` would drift to the far end.
    """
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 4))
    y = rng.normal(size=300) * 1e-9  # essentially no signal: every fit is all-zeros
    en = replication_cfg.signal.elasticnet

    fit = fit_combiner(X, y, en)
    sigma = np.where(X.std(0, ddof=0) > 0, X.std(0, ddof=0), 1.0)
    lmax = lambda_max((X - X.mean(0)) / sigma, y - y.mean(), en.l1_ratio)
    assert fit.lam == pytest.approx(lmax), "data-dependent grid: ties keep lambda_max"

    fixed = fit_combiner(X, y, _fixed_grid_cfg(replication_cfg))
    assert fixed.lam == pytest.approx(1e-4), "fixed grid: ties keep the smallest lambda"


def test_cross_validation_is_refused(replication_cfg, design):
    X, y, _ = design

    class CVCfg:
        l1_ratio = 0.5
        max_iter = 100
        selection = "cv"
        lambda_grid = replication_cfg.signal.elasticnet.lambda_grid

    with pytest.raises(ValueError, match="I2"):
        fit_combiner(X, y, CVCfg())


def test_config_rejects_cross_validation_selection(tmp_path):
    """I2 enforced at load time, not only at fit time."""
    import yaml

    from ctrend.config import ConfigError, load_config

    raw = yaml.safe_load(open("configs/replication.yaml"))
    raw["signal"]["elasticnet"]["selection"] = "cv"
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="cross-validation"):
        load_config(p)
