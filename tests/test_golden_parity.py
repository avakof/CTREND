"""Integration parity against the SPEC §5 golden — WITHOUT touching the golden (I3).

``tests/golden/test_cenet_golden.py`` is read-only and imports only numpy /
sklearn / scipy; it never executes ``src/``. It therefore cannot detect a
divergence in the production signal core, and "the golden is green" is false
comfort about code the golden never runs.

This file closes that gap: it drives the *production* CS-C-ENet core over a
Dataset seeded with the golden's exact constants and asserts the same facts.

Alignment check worth noting: the golden's holdout at ``t = T-1 = 89`` smooths
pairs ``[37, 88]`` and multiplies by ``Z[88]``. The engine's emission at signal
week 88 — labelled as the forecast for target week 89 — smooths exactly the same
pairs and uses exactly the same signal row. The two constructions coincide,
which is the concrete evidence for the ``forecast_alignment: t_plus_1``
resolution in DECISIONS.md.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import spearmanr

from ctrend.data.dataset import Dataset
from ctrend.data.truncation import PinnedTruncation
from ctrend.signal.engine import ctrend_at
from ctrend.signal.state import WalkForwardState
from fixtures.golden_panel import GOLDEN, build_golden_panel


@pytest.fixture(scope="module")
def golden_ds(tmp_path_factory, replication_cfg):
    root = tmp_path_factory.mktemp("golden_panel")
    root, cal, Z, R = build_golden_panel(root)
    # Truncation must not bite: the golden applies none. Pinning to +/-inf keeps
    # the A5 channel entirely out of this comparison.
    ds = Dataset.open(
        root, replication_cfg, truncation=PinnedTruncation(-np.inf, np.inf), calendar=cal
    )
    return ds, Z, R


def test_production_core_reproduces_the_golden(golden_ds, replication_cfg):
    ds, Z, R = golden_ds
    cw = ctrend_at(ds, replication_cfg, 88)

    assert cw.n_pooled == 9000, f"pooled n drifted: {cw.n_pooled}"
    assert cw.target_week == 89
    assert set(cw.selected.tolist()) == set(GOLDEN.PLANTED), (
        f"selection drifted: {cw.selected.tolist()}"
    )
    assert cw.lam == pytest.approx(0.004641588833612782, rel=1e-12), cw.lam

    # 7 nonzero coefficients, 5 positive: 22 and 27 carry negative theta and are
    # correctly excluded by the theta_j > 0 rule (golden docstring).
    nonzero = np.flatnonzero(cw.theta != 0).tolist()
    assert nonzero == [0, 3, 7, 12, 20, 22, 27], nonzero

    ic = spearmanr(cw.values, R[89])[0]
    assert ic > 0, f"holdout IC not positive: {ic}"
    assert ic == pytest.approx(0.088, abs=0.002), ic


def test_pooled_design_shape_matches_the_golden(golden_ds, replication_cfg):
    ds, Z, R = golden_ds
    state = WalkForwardState(GOLDEN.J, replication_cfg.signal)
    for week in range(0, 89):
        state.ingest(ds.asof(week, lookback=1))
    X, y = state.pooled(88)
    assert X.shape == (9000, GOLDEN.J)
    assert y.shape == (9000,)
    # golden: `for t in range(M + 1, T - 1)` -> training targets 53..88
    assert [b.target for b in state._pool] == list(range(53, 89))


def test_smoothed_window_is_right_exclusive(golden_ds, replication_cfg):
    """The pair at week t embeds r_t and must NOT enter smoothed(t)."""
    ds, Z, R = golden_ds
    state = WalkForwardState(GOLDEN.J, replication_cfg.signal)
    for week in range(0, 60):
        state.ingest(ds.asof(week, lookback=1))
    a, b = state.smoothed(53)
    expect_a = np.mean([state._alpha[w] for w in range(1, 53)], axis=0)
    assert np.array_equal(a, expect_a)
    assert not state.has_smoothed(52), "smoothing must not consume the unwritten week-0 pair"
