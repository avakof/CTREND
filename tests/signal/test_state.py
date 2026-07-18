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


def test_first_pool_target_is_week_53(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    assert [b.target for b in st._pool] == list(range(53, 61))
    assert st.pool_size(Week(55)) == 3


def test_pool_is_expanding_and_week_censored(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    X55, y55 = st.pooled(Week(55))
    X60, y60 = st.pooled(Week(60))
    assert len(y55) < len(y60)
    assert X60[: len(y55)].tobytes() == X55.tobytes(), "expanding pool is append-only"


def test_pooled_blocks_are_cross_sectionally_demeaned(ds, replication_cfg):
    st = _fed(ds, replication_cfg, 60)
    for block in st._pool:
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
