"""Invariant I1 — no look-ahead. THE M0 deliverable (SPEC §6 M0).

SPEC §6 M0, verbatim: "build signals through week *t* on a fixture, replace all
data after *t* with random noise, and assert CTREND at *t* is bit-identical."

The A5 subtlety, handled deliberately rather than by accident
-------------------------------------------------------------
``configs/replication.yaml`` sets ``truncation_mode: full_sample``. Per SPEC §8
ambiguity A5 the paper's full-sample return truncation **is itself a mild
look-ahead**, knowingly accepted for replication fidelity. A naive
"bit-identical under future noise" assertion would therefore fail for a
SPEC-sanctioned reason.

So the strict bit-identity assertion (:func:`test_bit_identical_under_future_noise_expanding`)
runs under ``expanding``, where the A5 channel is **closed**. Under
``full_sample`` the leak is not skipped or tolerated — it is *pinned down*:
:func:`test_full_sample_leakage_is_confined_to_truncation` proves that the
entire difference is the two threshold scalars, by holding those two scalars
fixed and showing bit-identity returns. No test here is skipped, weakened, or
run at a tolerance.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import duckdb
import numpy as np
import pytest

from ctrend.calendar import Week, WeekIndex
from ctrend.config import Config
from ctrend.data.dataset import Dataset
from ctrend.data.frozen import base_root, exposes_future, is_frozen
from ctrend.data.store import DuckDBPanelStore
from ctrend.data.truncation import (
    ExpandingTruncation,
    FullSampleTruncation,
    PinnedTruncation,
)
from ctrend.data.types import CausalityError
from ctrend.signal.engine import run
from ctrend.signal.state import WalkForwardState
from fixtures.poison import poison_partitions_after
from fixtures.synthetic import build_panel

N_WEEKS = 130
T_SPLIT = Week(100)  # 30 weeks of future for the noise to live in
# GT-8: under `smoothing: window_mean` the in-sample block at signal week w is
# the M weeks ending at w, so the first emission is target 53 -- matching the
# authors (first forecast index 53 -> 201416 + 52 = 201516) and SPEC 6 M3's
# "week 53 onward". The old 54 was an artifact of the trailing-mean pool.
FIRST_CTREND = 53


# --------------------------------------------------------------------------- #
# panels and runs (built once, reused; the engine is the expensive part)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def panels(tmp_path_factory):
    base = tmp_path_factory.mktemp("panels")
    made: dict[tuple, object] = {}

    def get(noise_after=None, noise_seed=None):
        key = (noise_after, noise_seed)
        if key not in made:
            root = base / f"p_{noise_after}_{noise_seed}"
            made[key] = build_panel(
                root, n_weeks=N_WEEKS, noise_after=noise_after, noise_seed=noise_seed
            )
        return made[key]

    return get


def _dataset(spec, cfg, mode: str, threads: int = 1) -> Dataset:
    lo, hi = cfg.returns.truncate_lower_pct, cfg.returns.truncate_upper_pct
    policy = {
        "expanding": lambda: ExpandingTruncation(lo, hi),
        "full_sample": lambda: FullSampleTruncation(lo, hi),
    }[mode]()
    return Dataset.open(
        spec.root, cfg, truncation=policy, calendar=spec.calendar, threads=threads
    )


class History:
    """Every CTREND the engine produced, flattened for a bitwise comparison."""

    def __init__(self, weeks):
        self.weeks = list(weeks)
        self.values = np.concatenate([w.values for w in self.weeks])
        self.index = np.concatenate(
            [np.stack([np.full(len(w.coins), int(w.target_week)), w.coins], 1) for w in self.weeks]
        )
        self.lam = np.array([w.lam for w in self.weeks])
        self.theta = np.vstack([w.theta for w in self.weeks])
        self.selected = [w.selected.tolist() for w in self.weeks]


_RUNS: dict[tuple, History] = {}


def _history(spec, cfg, mode, through=T_SPLIT) -> History:
    key = (str(spec.root), mode, int(through))
    if key not in _RUNS:
        ds = _dataset(spec, cfg, mode)
        _RUNS[key] = History(run(ds, cfg, through=Week(int(through))))
        ds.close()
    return _RUNS[key]


# --------------------------------------------------------------------------- #
# 1. THE M0 DoD, literally — bit-identity with the A5 channel closed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_bit_identical_under_future_noise_expanding(panels, replication_cfg, seed):
    clean = _history(panels(), replication_cfg, "expanding")
    dirty = _history(panels(T_SPLIT, seed), replication_cfg, "expanding")

    # Non-vacuity guards: a NaN payload would make any equality check pass.
    assert len(clean.weeks) > 0
    assert [int(w.target_week) for w in clean.weeks] == list(range(FIRST_CTREND, int(T_SPLIT) + 2))
    assert all(w.selected.size > 0 for w in clean.weeks), "empty selection => NaN CTREND"
    assert np.isfinite(clean.values).all()
    assert clean.values.size > 1000

    # The whole history, not just the last week: a leak at week 60 that washes
    # out by week 100 must still fail.
    assert clean.values.tobytes() == dirty.values.tobytes()  # BITWISE, not allclose
    assert np.array_equal(clean.index, dirty.index)
    assert np.array_equal(clean.lam, dirty.lam)
    assert np.array_equal(clean.theta, dirty.theta)
    assert clean.selected == dirty.selected


# --------------------------------------------------------------------------- #
# 2. non-vacuity: the instrument must be capable of changing the answer
# --------------------------------------------------------------------------- #
def test_noise_actually_changes_something(panels, replication_cfg):
    """The most important test in the file.

    Without it, test 1 passes trivially for an engine that ignores all data.
    Corrupting *before* the asof week must move CTREND at the asof week.
    """
    clean = _history(panels(), replication_cfg, "expanding")
    early = _history(panels(int(T_SPLIT) - 5, 1), replication_cfg, "expanding")
    assert clean.values.tobytes() != early.values.tobytes(), (
        "corrupting data at week 95 left CTREND at week 100 unchanged — the "
        "engine is not reading the panel, so the bit-identity test is vacuous"
    )


# --------------------------------------------------------------------------- #
# 3. the A5 crux: under full_sample the leak is EXACTLY the two thresholds
# --------------------------------------------------------------------------- #
def test_full_sample_leakage_is_confined_to_truncation(panels, replication_cfg):
    clean_spec, noisy_spec = panels(), panels(T_SPLIT, 1)

    a = _history(clean_spec, replication_cfg, "full_sample")
    b = _history(noisy_spec, replication_cfg, "full_sample")
    assert a.values.tobytes() != b.values.tobytes(), (
        "full_sample showed no leak — the A5 channel is not being exercised"
    )

    ds_clean = _dataset(clean_spec, replication_cfg, "full_sample")
    bounds = ds_clean.asof(T_SPLIT).truncation
    assert bounds.uses_future_data is True
    assert bounds.source_weeks[1] > T_SPLIT

    # Hold the two A5 scalars fixed. If anything *other* than truncation leaked,
    # the difference would survive this and the assertion below would fail.
    pin = PinnedTruncation(bounds.lower, bounds.upper)
    ds_a = Dataset.open(clean_spec.root, replication_cfg, truncation=pin,
                        calendar=clean_spec.calendar)
    ds_b = Dataset.open(noisy_spec.root, replication_cfg, truncation=pin,
                        calendar=noisy_spec.calendar)
    a2 = History(run(ds_a, replication_cfg, through=T_SPLIT))
    b2 = History(run(ds_b, replication_cfg, through=T_SPLIT))
    assert a2.values.tobytes() == b2.values.tobytes(), (
        "leakage survives pinned thresholds — a channel other than A5 exists"
    )
    assert np.array_equal(a2.theta, b2.theta)
    for d in (ds_clean, ds_a, ds_b):
        d.close()


# --------------------------------------------------------------------------- #
# 4. the leak signature is declared, measured, and ratcheted
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode,expect", [("expanding", False), ("full_sample", True)])
def test_truncation_declares_its_own_leakage(panels, replication_cfg, mode, expect):
    ds = _dataset(panels(), replication_cfg, mode)
    tr = ds.asof(T_SPLIT).truncation
    assert tr.uses_future_data is expect
    assert (tr.source_weeks[1] > T_SPLIT) is expect
    # Ratchet: if M2 or M4 later opens a second sanctioned leak, this fails and
    # forces a DECISIONS.md row. That is the point.
    assert ds.leakage_channels() == (
        frozenset({"A5_truncation"}) if expect else frozenset()
    )
    ds.close()


# --------------------------------------------------------------------------- #
# 5. the poison proof: asof physically never opens a future partition
# --------------------------------------------------------------------------- #
def test_asof_never_opens_future_partitions(tmp_path, replication_cfg):
    spec = build_panel(tmp_path / "poisoned", n_weeks=N_WEEKS)
    poison_partitions_after(spec.root, int(T_SPLIT))

    # `expanding`, because full_sample truncation is *defined* to scan the whole
    # sample and would legitimately hit the poison (that is the A5 channel).
    ds = Dataset.open(
        spec.root,
        replication_cfg,
        truncation=ExpandingTruncation(0.005, 0.995),
        calendar=spec.calendar,
    )
    win = ds.asof(T_SPLIT, lookback=1)  # must not raise
    assert win.eligible.any()

    # ...and the poison is real: a full scan blows up.
    with pytest.raises(duckdb.Error):
        ds._store._con.execute("SELECT count(*) FROM panel_raw").fetchone()
    ds.close()


# --------------------------------------------------------------------------- #
# 6-8. the window is a value, not a handle
# --------------------------------------------------------------------------- #
def test_window_is_irreversibly_frozen(panels, replication_cfg):
    ds = _dataset(panels(), replication_cfg, "expanding")
    win = ds.asof(T_SPLIT)
    for arr in (win.signals, win.excess_returns, win.market_cap, win.eligible, win.coins):
        assert is_frozen(arr)
        with pytest.raises(ValueError):
            arr.flags.writeable = True
        assert not exposes_future(arr)
        assert isinstance(base_root(arr), bytes)  # NOT isinstance(arr.base, bytes)
    ds.close()


def test_window_holds_no_handle_to_the_source(panels, replication_cfg):
    ds = _dataset(panels(), replication_cfg, "expanding")
    win = ds.asof(T_SPLIT)
    forbidden = (Dataset, DuckDBPanelStore, duckdb.DuckDBPyConnection, Path, Config, WeekIndex)
    for f in dataclasses.fields(win):
        assert not isinstance(getattr(win, f.name), forbidden), f.name
    assert not hasattr(win, "__dict__")  # slots=True: no attribute injection
    ds.close()


def test_asof_refuses(panels, replication_cfg):
    ds = _dataset(panels(), replication_cfg, "expanding")
    win = ds.asof(T_SPLIT)
    with pytest.raises(CausalityError):
        win.at(+1)
    with pytest.raises(CausalityError):
        ds.asof(Week(int(ds.calendar.last_week) + 1))
    assert bool((win.weeks <= int(T_SPLIT)).all())
    assert np.array_equal(win.coins, np.sort(win.coins))
    assert win.provenance.max_week_scanned == T_SPLIT
    ds.close()


# --------------------------------------------------------------------------- #
# 9. a death in the future is invisible today (A4)
# --------------------------------------------------------------------------- #
def test_delisting_registry_hides_future_deaths(panels, replication_cfg):
    spec = panels()
    ds = _dataset(spec, replication_cfg, "expanding")
    dead, d = spec.dead_coin, Week(spec.dead_week)

    assert dead not in ds.asof(Week(int(d) - 1)).delisted_map()
    assert ds.asof(Week(int(d) - 1)).eligible_at(Week(int(d) - 1))[dead] is True
    assert dead in ds.asof(d).delisted_map()
    assert ds.asof(d).delisted_map()[dead] == int(d)
    # ...and it stays dead
    assert dead in ds.asof(Week(int(d) + 10)).delisted_map()
    ds.close()


# --------------------------------------------------------------------------- #
# 10. bit-identity is an ordering property
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("threads", [1, 2, 4, 8])
def test_row_order_is_thread_invariant(panels, replication_cfg, threads):
    """Pins the `ORDER BY week_id, coin_id` guarantee tests 1 and 3 depend on."""
    spec = panels()
    ref = _dataset(spec, replication_cfg, "expanding", threads=1)
    got = _dataset(spec, replication_cfg, "expanding", threads=threads)
    a, b = ref.asof(T_SPLIT), got.asof(T_SPLIT)
    assert a.excess_returns.tobytes() == b.excess_returns.tobytes()
    assert a.signals.tobytes() == b.signals.tobytes()
    assert a.coins.tobytes() == b.coins.tobytes()
    ref.close()
    got.close()


# --------------------------------------------------------------------------- #
# 11. the accumulator is the one object outside the asof contract
# --------------------------------------------------------------------------- #
def test_accumulator_refuses_out_of_order_weeks(panels, replication_cfg):
    ds = _dataset(panels(), replication_cfg, "expanding")
    state = WalkForwardState(28, replication_cfg.signal)
    win = ds.asof(Week(10))
    state.ingest(win)
    with pytest.raises(CausalityError):
        state.ingest(win)  # same week again
    with pytest.raises(CausalityError):
        state.ingest(ds.asof(Week(9)))  # backwards
    ds.close()
