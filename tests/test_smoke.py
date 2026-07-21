"""Smoke test — the M0 pipeline runs end to end and produces sane CTREND.

SPEC §6 M3: "CTREND produced for every week from week 53 onward." With M = 52 the
earliest full smoothing window closes at signal week 52, but the pool of
combining targets is still empty there, so the first ENet-combined CTREND is for
target week 53 under GT-8 ``smoothing: window_mean``.
"""

from __future__ import annotations

import numpy as np
import pytest

from ctrend.config import load_config
from ctrend.data.dataset import Dataset
from ctrend.data.schema import SIGNAL_COLUMNS, validate_panel
from ctrend.signal.engine import ctrend_frame, run
from fixtures.synthetic import build_panel

N_WEEKS = 130


@pytest.fixture(scope="module")
def fixture_ds(tmp_path_factory, replication_cfg):
    spec = build_panel(tmp_path_factory.mktemp("smoke"), n_weeks=N_WEEKS)
    ds = Dataset.open(spec.root, replication_cfg, calendar=spec.calendar)
    yield spec, ds
    ds.close()


def test_fixture_satisfies_the_spec_contract(fixture_ds):
    spec, ds = fixture_ds
    assert spec.n_weeks >= 120, "SPEC §4.3 needs M=52 plus a training window"
    win = ds.asof(spec.n_weeks - 1, lookback=1)
    z = win.signals[-1][win.eligible[-1]]
    # SPEC §4.2: "weekly cross-sectional ranks land in [-0.5, +0.5]"
    assert z.min() >= -0.5 - 1e-12 and z.max() <= 0.5 + 1e-12
    assert len(SIGNAL_COLUMNS) == 28


def test_curated_panel_validates(fixture_ds):
    spec, ds = fixture_ds
    df = ds._store.window(0, 10, ds.asof(10).truncation)
    df["weekly_return"] = df["excess_return"]
    validate_panel(df)


def test_ctrend_is_produced_for_every_week_from_54(fixture_ds, replication_cfg):
    spec, ds = fixture_ds
    weeks = list(run(ds, replication_cfg))
    targets = [int(w.target_week) for w in weeks]
    # GT-8: first target is 53 (M weeks ending at signal week 52), matching
    # SPEC 6 M3 "week 53 onward" and the authors' 201516.
    assert targets == list(range(53, N_WEEKS + 1)), targets[:5] + targets[-3:]

    for w in weeks:
        assert np.isfinite(w.values).all(), f"non-finite CTREND at week {w.target_week}"
        assert w.selected.size > 0, f"empty selection at week {w.target_week}"
        assert len(w.values) == len(w.coins) >= replication_cfg.signal.min_cross_section
        # GT-9: the grid is data-dependent, so lambda is no longer drawn from a
        # fixed set. It must still be a positive finite scalar on (0, lambda_max].
        assert np.isfinite(w.lam) and w.lam > 0
        assert int(w.signal_week) == int(w.target_week) - 1


def test_planted_indicators_are_recovered(fixture_ds, replication_cfg):
    """The signal core is real, not a stub: it finds the structure that is there."""
    spec, ds = fixture_ds
    weeks = list(run(ds, replication_cfg))
    planted = {0, 3, 7, 12, 20}
    hit = [set(w.selected.tolist()) >= planted for w in weeks]
    assert sum(hit) / len(hit) > 0.9, f"planted set recovered in only {sum(hit)}/{len(hit)} weeks"


def test_ctrend_frame_shape(fixture_ds, replication_cfg):
    spec, ds = fixture_ds
    frame = ctrend_frame(ds, replication_cfg, through=60)
    assert set(frame.columns) == {"target_week", "coin_id", "ctrend"}
    assert frame["target_week"].min() == 53 and frame["target_week"].max() == 61
    assert frame["ctrend"].notna().all()


def test_configs_load_and_forbid_cross_validation():
    for name in ("replication", "live"):
        cfg = load_config(f"configs/{name}.yaml")
        # Invariant I2 — AICc only.
        assert cfg.signal.elasticnet.selection == "aicc"
        assert cfg.signal.elasticnet.l1_ratio == 0.5
        assert cfg.signal.estimation_window_weeks == 52
        assert cfg.universe.delisting_policy == "last_price"  # A4
        assert cfg.indicators.rank_map_range == (-0.5, 0.5)
    # GT-2: both modes now truncate daily and per-day cross-sectionally, which is
    # what the authors actually do and contains no look-ahead. The old
    # full_sample/expanding split rested on A5's mistaken premise.
    for f in ("configs/replication.yaml", "configs/live.yaml"):
        assert load_config(f).returns.truncation_mode == "daily_cross_sectional"
    # Ground-truth flags that must not silently drift back (I2).
    rep = load_config("configs/replication.yaml")
    assert rep.indicators.macd_denominator == "slow"  # GT-4
    assert rep.indicators.chaikin_window == 21  # GT-5
    assert rep.signal.smoothing == "window_mean"  # GT-8
    assert rep.signal.elasticnet.aicc_k == "nonzero"  # GT-10
    assert rep.signal.demean == "returns_only"  # GT-11
    assert rep.evaluation.tstat_method == "ols"  # GT-12
    # A6: the authors' resampler look-ahead must never be enabled in live mode.
    assert load_config("configs/live.yaml").indicators.liu_resample_lastfix == "corrected"


def test_signal_module_never_imports_cross_validation():
    """I2 as a structural fact, not a promise."""
    import pathlib

    src = pathlib.Path("src/ctrend/signal")
    banned = ("model_selection", "cross_val", "GridSearch", "ElasticNetCV", "LassoCV")
    for f in src.rglob("*.py"):
        for lineno, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("#")[0]
            if not (code.lstrip().startswith("import ") or code.lstrip().startswith("from ")):
                continue  # prose in a docstring may name the banned thing
            for b in banned:
                assert b not in code, f"{f}:{lineno} pulls in {b} — I2 forbids CV"


def test_signal_never_imports_the_evaluation_view():
    """The M4 accounting surface must stay unreachable from the signal core."""
    import pathlib

    for f in pathlib.Path("src/ctrend/signal").rglob("*.py"):
        for line in f.read_text().splitlines():
            assert "evaluation_view" not in line.split("#")[0], f
