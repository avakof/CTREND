"""SPEC §4.3 step 4 — ElasticNet combining and AICc lambda selection (I2)."""

import numpy as np
import pytest
from sklearn.linear_model import ElasticNet

from ctrend.signal.combine import fit_combiner, lambda_grid


@pytest.fixture
def design():
    rng = np.random.default_rng(3)
    n, J = 4000, 28
    X = rng.normal(size=(n, J))
    theta = np.zeros(J)
    theta[[1, 4, 9]] = [0.8, -0.6, 0.4]
    y = X @ theta + rng.normal(0, 1.0, n)
    return X, y, theta


def test_grid_is_25_log_spaced_points_from_1e_4_to_1(replication_cfg):
    g = lambda_grid(replication_cfg.signal.elasticnet)
    assert len(g) == 25
    assert g[0] == pytest.approx(1e-4) and g[-1] == pytest.approx(1.0)
    assert np.array_equal(g, np.logspace(-4, 0, 25))


def test_aicc_choice_matches_an_independent_recomputation(design, replication_cfg):
    X, y, _ = design
    cfg = replication_cfg.signal.elasticnet
    fit = fit_combiner(X, y, cfg)

    best = None
    for lam in np.logspace(-4, 0, 25):
        en = ElasticNet(alpha=lam, l1_ratio=0.5, max_iter=20000).fit(X, y)
        k = int((en.coef_ != 0).sum()) + 1
        n = len(y)
        sse = float(((y - en.predict(X)) ** 2).sum())
        aicc = n * np.log(sse / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1)
        if best is None or aicc < best[0]:
            best = (aicc, lam)
    assert fit.lam == best[1]
    assert fit.aicc == pytest.approx(best[0], rel=1e-12)


def test_selection_keeps_only_strictly_positive_theta(design, replication_cfg):
    X, y, true_theta = design
    fit = fit_combiner(X, y, replication_cfg.signal.elasticnet)
    sel = np.where(fit.theta > 0)[0]
    assert 1 in sel and 4 not in sel, "index 4 has a negative loading and must be dropped"
    assert (fit.theta[sel] > 0).all()


def test_ties_favour_the_smallest_lambda(replication_cfg):
    """Strict `<` in the AICc comparison; a `<=` would drift to the largest lambda."""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 4))
    y = rng.normal(size=300) * 1e-9  # essentially no signal: every fit is all-zeros
    fit = fit_combiner(X, y, replication_cfg.signal.elasticnet)
    assert fit.lam == pytest.approx(1e-4)


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
