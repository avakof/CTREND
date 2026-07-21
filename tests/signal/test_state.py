"""Walk-forward accumulator — the one object outside the ``Dataset.asof`` contract."""

import numpy as np
import pytest

from ctrend.calendar import Week
from ctrend.data.dataset import Dataset
from ctrend.data.frozen import is_frozen
from ctrend.data.truncation import ExpandingTruncation
from ctrend.data.types import CausalityError
from ctrend.signal.state import WalkForwardState
from fixtures.synthetic import build_panel


@pytest.fixture(scope="module")
def ds(tmp_path_factory, replication_cfg):
    spec = build_panel(tmp_path_factory.mktemp("state"), n_weeks=130)
    d = Dataset.open(
        spec.root, replication_cfg,
        truncation=ExpandingTruncation(0.005, 0.995), calendar=spec.calendar,
    )
    yield spec, d
    d.close()


def _fed(ds, cfg, upto):
    _, d = ds
    st = WalkForwardState(28, cfg.signal)
    for w in range(upto + 1):
        st.ingest(d.asof(Week(w)))
    return st


def test_week_zero_yields_no_pair(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 0)
    assert st._alpha == {} and st.skipped[0] == "no t-1 row in window"


def test_everything_stored_is_frozen_and_derived(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    for w, a in st._alpha.items():
        assert is_frozen(a) and a.shape == (28,)
        assert is_frozen(st._beta[w])
    for block in st._pool:
        assert is_frozen(block.X) and is_frozen(block.y)
        assert block.X.shape[1] == 28
    # derived only: no panel-shaped arrays are retained
    assert not hasattr(st, "_signals") and not hasattr(st, "_returns")


def test_smoothing_window_is_right_exclusive(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    a, b = st.smoothed(Week(55))
    assert np.array_equal(a, np.mean([st._alpha[w] for w in range(3, 55)], axis=0))
    assert np.array_equal(b, np.mean([st._beta[w] for w in range(3, 55)], axis=0))
    assert 55 not in range(3, 55), "the pair at t embeds r_t and must be excluded"


def test_smoothing_needs_a_complete_window(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    assert not st.has_smoothed(Week(52))  # would need the unwritten week-0 pair
    assert st.has_smoothed(Week(53))
    with pytest.raises(CausalityError):
        st.smoothed(Week(52))


def _trailing_cfg(cfg):
    """The superseded regime: per-week trailing means, expanding pool."""
    from dataclasses import replace

    return replace(cfg, signal=replace(cfg.signal, smoothing="trailing_mean",
                                       training_window="expanding"))


# --------------------------------------------------------------------------- #
# GT-8 — each flag must CHANGE behaviour.
#
# These exist because `smoothing: window_mean` and `training_window: rolling:52`
# were declared in config, validated by ctrend.config, and silently ignored by
# the engine while the whole suite stayed green. A flag no test can distinguish
# is indistinguishable from a comment (invariant I2).
# --------------------------------------------------------------------------- #
def test_window_mean_is_the_default_regime(replication_cfg):
    st = WalkForwardState(28, replication_cfg.signal)
    assert st.smoothing == "window_mean"
    assert replication_cfg.signal.training_window == "rolling:52"


def test_smoothing_flag_changes_the_pooled_design(ds, replication_cfg):
    """window_mean vs trailing_mean must not produce the same design."""
    win = _fed(ds, replication_cfg, 60)
    tra = _fed(ds, _trailing_cfg(replication_cfg), 60)
    Xw, yw = win.pooled(Week(60))
    Xt, yt = tra.pooled(Week(60))
    assert Xw.shape != Xt.shape or Xw.tobytes() != Xt.tobytes(), (
        "smoothing flag had no effect — GT-8 is not wired through"
    )


def test_window_mean_applies_ONE_pair_to_every_training_week(ds, replication_cfg):
    """The defining property of GT-8.

    `fEstFamaMacBethPanel.m:156-157` collapses the window to a single
    (alpha_bar, beta_bar); `fPredictFamaMacBethPanel.m:67` applies it to every
    in-sample week. So each block of the design must equal `ab + z_s * bb` for
    the *same* pair -- the one the engine will also use for the out-of-sample
    forecast, i.e. `smoothed(week + 1)`.
    """
    st = _fed(ds, replication_cfg, 60)
    ab, bb = st.smoothed(Week(61))
    X, _ = st.pooled(Week(60))

    row = 0
    for s in st.training_targets(Week(60)):
        z, _ = st._obs[s]
        f = ab + z * bb
        expect = f - f.mean(0)
        got = X[row : row + len(z)]
        assert np.array_equal(got, expect), f"training week {s} used a different pair"
        row += len(z)
    assert row == len(X)


def test_training_window_flag_changes_the_pool(ds, replication_cfg):
    """rolling:52 must censor what expanding retains."""
    from dataclasses import replace

    roll = _fed(ds, replication_cfg, 60)
    exp_cfg = replace(replication_cfg,
                      signal=replace(replication_cfg.signal, training_window="expanding"))
    expa = _fed(ds, exp_cfg, 60)
    assert roll.pool_size(Week(60)) <= expa.pool_size(Week(60))
    assert min(roll.training_targets(Week(60))) > min(expa.training_targets(Week(60))), (
        "training_window flag had no effect — GT-8 is not wired through"
    )


def test_rolling_window_spans_M_weeks_ending_at_the_signal_week(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    targets = st.training_targets(Week(60))
    # [w+1-M, w] in this module's right-exclusive convention.
    assert max(targets) == 60
    assert min(targets) == max(1, 61 - replication_cfg.signal.estimation_window_weeks)


def test_trailing_mean_pool_is_expanding_and_week_censored(ds, replication_cfg):
    """Superseded regime, retained as an M5 sensitivity axis."""
    st = _fed(ds, _trailing_cfg(replication_cfg), 60)
    assert [b.target for b in st._pool] == list(range(53, 61))
    assert st.pool_size(Week(55)) == 3
    X55, y55 = st.pooled(Week(55))
    X60, y60 = st.pooled(Week(60))
    assert len(y55) < len(y60)
    assert X60[: len(y55)].tobytes() == X55.tobytes(), "expanding pool is append-only"


def test_pooled_design_is_cross_sectionally_demeaned(ds, replication_cfg):
    """GT-11: returns demeaned per week; forecasts demeaned per week too, but no
    time fixed effects enter the fit -- the combiner carries a global intercept."""
    st = _fed(ds, replication_cfg, 60)
    ab, bb = st.smoothed(Week(61))
    for s in st.training_targets(Week(60)):
        z, r = st._obs[s]
        f = ab + z * bb
        assert abs(float((r - r.mean()).mean())) < 1e-12
        assert np.abs((f - f.mean(0)).mean(0)).max() < 1e-12

    st_t = _fed(ds, _trailing_cfg(replication_cfg), 60)
    for block in st_t._pool:
        assert abs(float(block.y.mean())) < 1e-12
        assert np.abs(block.X.mean(0)).max() < 1e-12


def test_monotone_advance_is_enforced(ds, replication_cfg):
    spec, d = ds
    st = WalkForwardState(28, replication_cfg.signal)
    st.ingest(d.asof(Week(20)))
    with pytest.raises(CausalityError):
        st.ingest(d.asof(Week(20)))
    with pytest.raises(CausalityError):
        st.ingest(d.asof(Week(19)))
    st.ingest(d.asof(Week(21)))  # forward is fine
    assert st.high_water == 21


def test_empty_pool_is_an_error_not_a_silent_zero(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 10)
    with pytest.raises(CausalityError):
        st.pooled(Week(10))
