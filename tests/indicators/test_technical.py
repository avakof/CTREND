"""Property tests for the 28 indicators (SPEC §4.2, as corrected by GT-4…GT-7).

SPEC's original property list asserted things a faithful port FAILS -- stochastics on
[0,100] and NaN-until-warm-up for every family. Both were our misreading; the code
below asserts what the authors' implementation actually does, with the divergence
tests written so a silent regression to the old behaviour is caught.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ctrend.indicators.technical import (
    INDICATORS,
    NEEDS_HIGH_LOW,
    compute_indicators,
    ema,
    sma_expanding,
)


def _panel(n=300, seed=0, with_hl=True, scale=1.0):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.03, n)) * scale
    d = pd.DataFrame({
        "coin_id": 1,
        "date": pd.date_range("2015-01-01", periods=n),
        "close": close,
        "dollar_volume": np.abs(rng.normal(1e6, 2e5, n)),
    })
    if with_hl:
        d["high"] = close * (1 + np.abs(rng.normal(0, 0.02, n)))
        d["low"] = close * (1 - np.abs(rng.normal(0, 0.02, n)))
    return d


@pytest.fixture(scope="module")
def ind():
    return compute_indicators(_panel())


def test_exactly_28_named_indicators_in_fixed_order():
    """The elastic net's coefficient vector is positional — order is part of the spec."""
    assert len(INDICATORS) == 28
    assert len(set(INDICATORS)) == 28
    assert INDICATORS[0] == "sma_3d" and INDICATORS[-1] == "chaikin"


def test_rsi_is_zero_to_one_hundred(ind):
    v = ind["rsi"].dropna()
    assert len(v) > 100
    assert v.min() >= 0.0 and v.max() <= 100.0


@pytest.mark.parametrize("name", ["stochK", "stochD", "stochRSI"])
def test_stochastics_are_unit_scaled_not_percent(ind, name):
    """GT-6: the authors' stochastics are on [0,1]. SPEC said [0,100] — wrong."""
    v = ind[name].dropna()
    assert len(v) > 50
    assert v.min() >= 0.0 and v.max() <= 1.0
    assert v.max() <= 1.0 + 1e-12, "a [0,100] scaling would blow this assertion"


@pytest.mark.parametrize("w", [3, 20, 200])
def test_sma_family_has_no_warmup_nan(ind, w):
    """GT-7: expanding omitnan window. sma_200d is non-NaN from day 1, where the
    expanding mean of one point over its own value is exactly 1.0."""
    s = ind[f"sma_{w}d"]
    assert s.notna().all(), f"sma_{w}d must never be NaN on a clean series"
    assert s.iloc[0] == pytest.approx(1.0)


def test_volsma_family_has_no_warmup_nan(ind):
    for w in (3, 20, 200):
        assert ind[f"volsma_{w}d"].notna().all()


def test_macd_family_has_no_warmup_mask(ind):
    """PPO/PVO apply no warm-up NaN (unlike the unused fMACD)."""
    for c in ("macd", "macd_diff_signal", "volmacd", "volmacd_diff_signal"):
        assert ind[c].iloc[30:].notna().all(), c


def test_bollinger_sets_the_real_warmup(ind):
    """std/mean WITHOUT omitnan -> needs 20 consecutive clean closes. This family,
    not the 200-day SMA, is what actually gates universe entry."""
    for c in ("boll_low", "boll_mid", "boll_high", "boll_width"):
        s = ind[c]
        assert s.iloc[:19].isna().all(), f"{c} must be NaN before 20 closes"
        assert s.iloc[19:].notna().all(), c


def test_sma_over_close_is_invariant_under_price_rescaling():
    """SPEC §4.2 required property: scaling every price leaves the ratio unchanged."""
    a = compute_indicators(_panel(scale=1.0))
    b = compute_indicators(_panel(scale=1000.0))
    for w in (3, 20, 200):
        np.testing.assert_allclose(a[f"sma_{w}d"], b[f"sma_{w}d"], rtol=1e-9)
    for c in ("boll_mid", "boll_width"):
        np.testing.assert_allclose(a[c].dropna(), b[c].dropna(), rtol=1e-9)


def test_macd_divides_by_the_SLOW_ema_not_the_fast(ind):
    """GT-4, and the single most consequential indicator correction.

    The paper's body text says the difference is expressed as a percentage of the
    *fast* EMA; its own footnote 3 says this makes macd "equivalent to the percentage
    price oscillator (PPO)", which divides by the *slow* EMA — and `b02:199` calls
    `fPercentagePriceOscillator`. Footnote and code agree; the body text is wrong.
    """
    d = _panel()
    close = d["close"].to_numpy()
    f, s = ema(close, 12), ema(close, 26)
    slow_ver = (f - s) / s
    fast_ver = (f - s) / f
    got = ind["macd"].to_numpy()
    m = np.isfinite(got) & np.isfinite(slow_ver) & np.isfinite(fast_ver)
    np.testing.assert_allclose(got[m], slow_ver[m], rtol=1e-9)
    assert not np.allclose(got[m], fast_ver[m]), "fast/slow are indistinguishable here"


def test_ema_matches_the_matlab_recursion_exactly():
    """Assert the recursion itself, hand-computed, rather than a claim about pandas.

    `technical_indicators.m:110-164`: k = 2/(1+w), EMA[0] = NaN, and a missing
    previous EMA is seeded with the SMA at t-1 (which at t=1 is just x[0]).
    """
    x = _panel(n=40)["close"].to_numpy()
    w = 12
    k = 2.0 / (1.0 + w)
    got = ema(x, w)
    assert np.isnan(got[0]), "EMA[0] must be NaN"
    expect = x[1] * k + x[0] * (1 - k)      # seeded from SMA at t-1 == x[0]
    assert got[1] == pytest.approx(expect)
    for t in range(2, 40):
        assert got[t] == pytest.approx(x[t] * k + got[t - 1] * (1 - k))


def test_ema_coincides_with_pandas_only_after_the_seed():
    """A deliberate NON-divergence, recorded so it is not mistaken for a port bug.

    On a gapless series the SMA seeding differs from ``ewm(adjust=False)`` only at
    t = 0, so the two agree from t = 1 onward. The seeding rule earns its keep on
    series with leading or interior gaps, which is exactly what crypto panels have.
    """
    x = _panel(n=60)["close"].to_numpy()
    ours = ema(x, 12)
    theirs = pd.Series(x).ewm(span=12, adjust=False).mean().to_numpy()
    assert np.isnan(ours[0]) and np.isfinite(theirs[0])
    np.testing.assert_allclose(ours[1:], theirs[1:], rtol=1e-9)

    # With an interior gap the carry-forward rule keeps the level finite.
    y = x.copy()
    y[20:23] = np.nan
    gapped = ema(y, 12)
    assert np.isfinite(gapped[23:]).all(), "a gap must not poison the rest of the EMA"


def test_high_low_indicators_are_nan_without_high_low_and_others_survive():
    """The whole reason the H/L gap matters: these four go NaN, and under the
    authors' complete-case rule that removes the coin-week entirely."""
    got = compute_indicators(_panel(with_hl=False))
    for c in NEEDS_HIGH_LOW:
        assert got[c].isna().all(), f"{c} needs high/low"
    for c in set(INDICATORS) - NEEDS_HIGH_LOW:
        assert got[c].notna().any(), f"{c} must not depend on high/low"
    assert NEEDS_HIGH_LOW == {"stochK", "stochD", "cci", "chaikin"}


def test_chaikin_uses_a_21_day_window_with_min_10(ind):
    """GT-5: 21/10, not SPEC's guessed 20."""
    s = ind["chaikin"]
    assert s.iloc[:9].isna().all()
    assert s.iloc[12:].notna().any()


def test_chaikin_drops_zero_range_days_rather_than_treating_them_as_zero():
    d = _panel(n=60)
    d.loc[:, "high"] = d["close"]          # zero high-low range everywhere
    d.loc[:, "low"] = d["close"]
    got = compute_indicators(d)
    assert got["chaikin"].isna().all(), "zero-range days must become NaN, not 0"


def test_volsma_denominator_zero_becomes_nan():
    d = _panel(n=60)
    d.loc[30, "dollar_volume"] = 0.0
    got = compute_indicators(d)
    assert np.isnan(got.loc[30, "volsma_3d"])


def test_sma_expanding_matches_its_definition():
    x = np.arange(1.0, 11.0)
    got = sma_expanding(x, 5)
    assert got[0] == pytest.approx(1.0)
    assert got[2] == pytest.approx(2.0)          # mean(1,2,3)
    assert got[9] == pytest.approx(8.0)          # mean(6..10)


def test_nan_in_close_does_not_poison_the_whole_expanding_sma():
    d = _panel(n=60)
    d.loc[10, "close"] = np.nan
    got = compute_indicators(d)
    assert got["sma_3d"].iloc[20:].notna().all(), "omitnan must skip the hole"
