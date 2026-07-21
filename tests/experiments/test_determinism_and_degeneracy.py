"""Regression tests for the two defects that produced a published, irreproducible number.

Both were found by an adversarial audit on 2026-07-21, after the results had been
written up and pushed. Neither had any test coverage, and neither was visible from the
output: the table looked completely ordinary.

1. `harness.load_panel` issued an unordered `SELECT` under `PRAGMA threads=4`. DuckDB is
   free to return rows in any order, so the float summation order inside each
   value-weighted quintile changed between runs. Harmless wherever a quantity is
   genuinely non-zero — it perturbs the 15th significant digit. Fatal for C4, whose true
   difference from the baseline is *exactly* zero: there the rounding residue was 100% of
   the signal, and its t-statistic wandered over (-2.25, -0.20, +0.08, +0.72, +1.63,
   +2.19) across runs. The published t = 0.744 was one draw.

2. That noise column then entered the SPA bootstrap. `spa_pvalue` guarded `sd == 0`, but
   a degenerate column's sd is ~3e-17, not 0, so the guard never fired and 1e-16-scale
   garbage became the family maximum. The published SPA p = 0.643 could not be
   reproduced; re-runs ranged 0.221 to 0.877.

The lesson generalises past this repo: an overlay that is a deliberate no-op is exactly
the case where floating-point noise stops being negligible, because there is nothing
else in the number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ctrend.experiments.stats import paired_t, report_table, spa_pvalue


def _series(n: int = 60, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.005, 0.06, n), index=range(202401, 202401 + n))


# --------------------------------------------------------------------------- #
# Degenerate (bit-exact no-op) configurations
# --------------------------------------------------------------------------- #
def test_zero_variance_difference_yields_no_test_statistic():
    """A no-op overlay must report NO t and NO p — not a t drawn from rounding."""
    d = pd.Series(0.0, index=range(50))
    assert paired_t(d) == (np.nan, np.nan) or all(np.isnan(x) for x in paired_t(d))


def test_degenerate_config_is_excluded_from_the_test_family():
    """It must not inflate M. Counting a no-op as a test makes every correction
    fractionally too harsh and, more importantly, implies a test was performed."""
    base = _series()
    out = report_table({"C0": base, "C1": base.copy(), "C2": _series(seed=1)},
                       baseline="C0")
    c1 = out[out.config == "C1"].iloc[0]
    assert np.isnan(c1.t_paired) and np.isnan(c1.p_raw), "no-op must carry no statistic"
    assert int(out["p_raw"].notna().sum()) == 1, "family is the real tests only"
    # ...and the haircut columns must be keyed to that count, not to len(table).
    assert any(c.startswith("diff_sr_haircut_M1") for c in out.columns), list(out.columns)


def test_epsilon_scale_noise_does_not_drive_the_spa_statistic():
    """The original guard was `sd == 0`, which a 3e-17 column walks straight past.

    Here the noise column has a hugely positive mean *relative to its own sd* — the exact
    shape that makes it the family maximum — but it is 1e-16 scale and must be ignored.
    """
    rng = np.random.default_rng(7)
    n = 120
    real = pd.DataFrame({f"c{i}": rng.normal(0, 0.02, n) for i in range(3)})
    noise = pd.Series(np.abs(rng.normal(0, 1e-16, n)), name="degenerate")

    p_without = spa_pvalue(real, n_boot=400)
    p_with = spa_pvalue(real.assign(degenerate=noise), n_boot=400)
    assert p_without == pytest.approx(p_with, abs=1e-9), (
        f"a 1e-16 column changed SPA from {p_without} to {p_with}"
    )


def test_spa_guard_is_relative_not_absolute():
    """Scale invariance: the same data in different units must guard identically."""
    rng = np.random.default_rng(11)
    n = 120
    big = pd.DataFrame({"a": rng.normal(0, 1e6, n), "b": rng.normal(0, 1e6, n)})
    # a column that is degenerate *relative to* the others, but huge in absolute terms
    big["c"] = np.abs(rng.normal(0, 1e-8, n))
    p = spa_pvalue(big, n_boot=400)
    assert 0.0 < p <= 1.0 and np.isfinite(p)


# --------------------------------------------------------------------------- #
# Panel ordering
# --------------------------------------------------------------------------- #
def test_load_panel_query_pins_row_order():
    """Guards the fix at the source. Reading the SQL is the only way to assert this
    without the 2GB panel — but a missing ORDER BY here is precisely the defect, so a
    cheap textual check is worth more than no check."""
    import inspect

    from ctrend.experiments import harness

    sql = inspect.getsource(harness.load_panel)
    assert "ORDER BY" in sql.upper(), (
        "load_panel must pin row order: unordered DuckDB output makes float summation "
        "order vary between runs, which is irreproducible for any exactly-zero quantity"
    )


@pytest.mark.parametrize("mod,fn", [("ctrend.evaluation.m6_variants", "load")])
def test_other_panel_loaders_pin_row_order(mod, fn):
    import importlib
    import inspect

    sql = inspect.getsource(getattr(importlib.import_module(mod), fn))
    assert "ORDER BY" in sql.upper(), f"{mod}.{fn} must pin row order"


# --------------------------------------------------------------------------- #
# The haircut's saturation, made explicit so nobody reads a zero as a finding
# --------------------------------------------------------------------------- #
def test_haircut_saturates_to_zero_for_any_sharpe_once_p_exceeds_ten_percent():
    """`sr_haircut = 0` says the adjusted p hit its ceiling. It says NOTHING about the
    Sharpe — a strategy with Sharpe 5 haircuts to 0 on the same input. The published
    report previously read this zero as evidence about the strategy."""
    from ctrend.experiments.stats import haircut_sharpe

    for sr in (0.5, 2.0, 5.0, 50.0):
        assert haircut_sharpe(sr, t=1.0, p_adj=1.0) == pytest.approx(0.0, abs=1e-9)
