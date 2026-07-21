"""The 28 technical indicators (SPEC §4.2), ported from the authors' MATLAB.

Reference: `Utils/technical_indicators.m` and `b02CalculateIndicators.m`. The name
list is fixed by `b05CreateCTREND.m:78-82` and is neither extensible nor reorderable
without a DECISIONS.md entry -- the elastic net's coefficient vector is positional.

Ported quirks that are NOT bugs (each changes the universe or the values, and each
is cited where it is implemented):

* **GT-4** `macd`/`volmacd` are PPO/PVO -- the EMA difference over the **slow** EMA.
  The paper's body text says "fast"; its own footnote 3 says the normalization makes
  it "equivalent to the percentage price oscillator (PPO)", which divides by the slow
  EMA, and the code calls `fPercentagePriceOscillator`. The footnote and code agree.
* **GT-5** `chaikin` uses a 21-day window with a 10-observation minimum.
* **GT-6** `stochK`, `stochD`, `stochRSI` are on **[0, 1]**, not [0, 100]. Only `rsi`
  is on [0, 100]. Harmless downstream -- everything is rank-transformed -- but the
  property tests must assert the right range.
* **GT-7** SMA and volSMA use an **expanding** window with `omitnan`, so `sma_200d`
  is non-NaN from a coin's first day (where it equals exactly 1.0). PPO/PVO apply no
  warm-up mask either. The binding warm-up comes from the Bollinger family (20
  *consecutive* clean closes), `chaikin` (21/10), `cci` (20/10) and the stochastics.

The EMA is the authors' explicit recursion, **not** ``pandas.ewm(adjust=False)``:
smoothing ``2/(1+w)``, ``EMA[0] = NaN``, and a missing previous EMA is seeded with
the SMA at ``t-1`` (`technical_indicators.m:110-164`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["INDICATORS", "compute_indicators", "ema", "sma_expanding"]

#: Positional and authoritative — `b05CreateCTREND.m:78-82`.
INDICATORS: tuple[str, ...] = (
    *[f"sma_{d}d" for d in (3, 5, 10, 20, 50, 100, 200)],
    "macd", "macd_diff_signal",
    *[f"volsma_{d}d" for d in (3, 5, 10, 20, 50, 100, 200)],
    "volmacd", "volmacd_diff_signal",
    "rsi", "stochRSI", "stochK", "stochD",
    "boll_low", "boll_mid", "boll_high", "boll_width",
    "cci", "chaikin",
)
assert len(INDICATORS) == 28, len(INDICATORS)

#: Indicators that require daily high/low. Missing H/L makes these NaN, which under
#: `b05:115`'s complete-case rule removes the whole coin-week -- see cmc_ohlc.py.
NEEDS_HIGH_LOW: frozenset[str] = frozenset({"stochK", "stochD", "cci", "chaikin"})


def sma_expanding(x: np.ndarray, window: int) -> np.ndarray:
    """GT-7: mean over ``max(0, t-w+1)..t`` ignoring NaN. No warm-up mask."""
    s = pd.Series(x, dtype="float64")
    return s.rolling(window, min_periods=1).mean().to_numpy()


def ema(x: np.ndarray, window: int) -> np.ndarray:
    """The authors' EMA recursion (`technical_indicators.m:110-164`).

    Deliberately not vectorised through ``pandas.ewm``: that seeds differently and
    has no SMA fallback, which would shift every macd value.
    """
    n = len(x)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    k = 2.0 / (1.0 + window)
    sma_prev = sma_expanding(x, window)
    for t in range(1, n):
        prev = out[t - 1]
        if not np.isfinite(prev):
            prev = sma_prev[t - 1]  # seed from the SMA at t-1
        xt = x[t]
        if not np.isfinite(xt):
            out[t] = prev
            continue
        out[t] = xt * k + prev * (1.0 - k) if np.isfinite(prev) else xt
    return out


def _ppo(x: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """GT-4: (EMA_fast - EMA_slow) / EMA_slow, plus its signal-line difference."""
    f, s = ema(x, fast), ema(x, slow)
    with np.errstate(divide="ignore", invalid="ignore"):
        ppo = np.where(np.abs(s) > 0, (f - s) / s, np.nan)
    return ppo, ppo - ema(ppo, signal)


def _rsi(close: np.ndarray, window: int = 14) -> np.ndarray:
    """Wilder-smoothed RSI on [0, 100] (MATLAB ``rsindex``)."""
    d = np.diff(close, prepend=np.nan)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[~np.isfinite(d)] = np.nan
    dn[~np.isfinite(d)] = np.nan
    n = len(close)
    out = np.full(n, np.nan)
    if n <= window:
        return out
    au = np.nanmean(up[1 : window + 1])
    ad = np.nanmean(dn[1 : window + 1])
    for t in range(window, n):
        if t > window:
            u, v = up[t], dn[t]
            if np.isfinite(u) and np.isfinite(v):
                au = (au * (window - 1) + u) / window
                ad = (ad * (window - 1) + v) / window
        out[t] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / max(ad, 1e-300))
    return out


def _roll_min_max(x: np.ndarray, window: int, min_obs: int):
    s = pd.Series(x, dtype="float64")
    return (s.rolling(window, min_periods=min_obs).min().to_numpy(),
            s.rolling(window, min_periods=min_obs).max().to_numpy())


def _stoch(v: np.ndarray, lo_src: np.ndarray, hi_src: np.ndarray, window: int,
           min_obs: int) -> np.ndarray:
    """GT-6: scaled to [0, 1], NOT [0, 100]."""
    ll, _ = _roll_min_max(lo_src, window, min_obs)
    _, hh = _roll_min_max(hi_src, window, min_obs)
    rng = hh - ll
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(rng > 0, (v - ll) / rng, np.nan)


def _cci(close, low, high, window: int = 20, min_obs: int = 10,
         c: float = 0.015) -> np.ndarray:
    """Typical price vs its SMA, scaled by mean absolute deviation.

    `technical_indicators.m:798` measures the deviation against the **most recent**
    SMA rather than each window point's own SMA -- reproduced here.
    """
    tp = (close + low + high) / 3.0
    s = pd.Series(tp, dtype="float64")
    ma = s.rolling(window, min_periods=min_obs).mean()
    md = s.rolling(window, min_periods=min_obs).apply(
        lambda w: np.nanmean(np.abs(w - np.nanmean(w))), raw=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(md.to_numpy() > 0, (tp - ma.to_numpy()) / (c * md.to_numpy()),
                        np.nan)


def _chaikin(close, low, high, volume, window: int = 21, min_obs: int = 10):
    """GT-5. Two guards from `technical_indicators.m:275-290` are load-bearing:
    a non-positive high-low range becomes NaN (not 0), and a zero-volume window
    yields NaN. Availability is masked **jointly** across C/L/H/V first."""
    ok = np.isfinite(close) & np.isfinite(low) & np.isfinite(high) & np.isfinite(volume)
    c = np.where(ok, close, np.nan)
    lo = np.where(ok, low, np.nan)
    hi = np.where(ok, high, np.nan)
    v = np.where(ok, volume, np.nan)

    rng = hi - lo
    rng = np.where(rng > 0, rng, np.nan)  # zero-range days dropped, not treated as 0
    with np.errstate(divide="ignore", invalid="ignore"):
        ad = ((c - lo) - (hi - c)) / rng * v
    num = pd.Series(ad).rolling(window, min_periods=min_obs).sum().to_numpy()
    den = pd.Series(v).rolling(window, min_periods=min_obs).sum().to_numpy()
    den = np.where(den > 0, den, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return num / den


def _bollinger(close: np.ndarray, window: int = 20):
    """`std`/`mean` **without** omitnan (`technical_indicators.m:667-668`), so this
    family needs 20 *consecutive* clean closes and sets the real warm-up."""
    s = pd.Series(close, dtype="float64")
    mid = s.rolling(window, min_periods=window).mean().to_numpy()
    sd = s.rolling(window, min_periods=window).std(ddof=0).to_numpy()
    upper, lower = mid + 2 * sd, mid - 2 * sd
    with np.errstate(divide="ignore", invalid="ignore"):
        return (
            np.where(close > 0, lower / close, np.nan),
            np.where(close > 0, mid / close, np.nan),
            np.where(close > 0, upper / close, np.nan),
            np.where(np.abs(mid) > 0, (upper - lower) / mid, np.nan),  # /mid, not /close
        )


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Daily indicators for ONE coin, sorted ascending by date.

    Requires ``close`` and ``dollar_volume``; ``high``/``low`` may be absent or NaN,
    in which case the four :data:`NEEDS_HIGH_LOW` indicators are NaN.
    """
    d = df.sort_values("date")
    close = d["close"].to_numpy(dtype="float64")
    vol = d["dollar_volume"].to_numpy(dtype="float64")
    high = d["high"].to_numpy(dtype="float64") if "high" in d else np.full(len(d), np.nan)
    low = d["low"].to_numpy(dtype="float64") if "low" in d else np.full(len(d), np.nan)

    out: dict[str, np.ndarray] = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for w in (3, 5, 10, 20, 50, 100, 200):
            out[f"sma_{w}d"] = np.where(close > 0, sma_expanding(close, w) / close, np.nan)
        # b02:210-213 — a zero current volume makes the ratio NaN, not inf.
        vpos = np.where(vol > 0, vol, np.nan)
        for w in (3, 5, 10, 20, 50, 100, 200):
            out[f"volsma_{w}d"] = sma_expanding(vol, w) / vpos

    out["macd"], out["macd_diff_signal"] = _ppo(close)
    out["volmacd"], out["volmacd_diff_signal"] = _ppo(vol)

    rsi = _rsi(close)
    out["rsi"] = rsi
    out["stochRSI"] = _stoch(rsi, rsi, rsi, 14, 5)     # min 5 obs (b02:178)
    out["stochK"] = _stoch(close, low, high, 14, 14)
    out["stochD"] = sma_expanding(out["stochK"], 3)
    out["boll_low"], out["boll_mid"], out["boll_high"], out["boll_width"] = _bollinger(close)
    out["cci"] = _cci(close, low, high)
    out["chaikin"] = _chaikin(close, low, high, vol)

    res = pd.DataFrame({k: out[k] for k in INDICATORS}, index=d.index)
    res.insert(0, "date", d["date"].to_numpy())
    res.insert(0, "coin_id", d["coin_id"].to_numpy())
    return res
