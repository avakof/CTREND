"""Book-level overlays: volatility targeting (U2) and beta hedging (U4).

Both operate on the weekly return series rather than on positions. That is legitimate
here because scaling a linear book by a scalar known at t-1 is exactly equivalent to
scaling its realised return — but it is only legitimate if the scalar really is known
at t-1, which is why the `.shift(1)` in :func:`vol_target` is load-bearing and has its
own test.

Two ways these overlays flatter themselves if implemented carelessly:

* **Leverage is not free.** Scaling to k > 1 costs money twice: k times the usual
  rebalancing, plus the cost of adjusting the leverage itself, |k_t - k_{t-1}| against
  the standing book. Omit the second term and vol targeting looks like a free Sharpe
  improvement.
* **Funding is not free either, and its sign is easy to invert.** A short perpetual
  RECEIVES funding when the rate is positive, which it usually was over 2022-26. Get
  the sign backwards and a cost becomes a subsidy. Results are reported with and
  without funding credited so the reader can see how much of the hedge is the hedge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 52.0

__all__ = ["vol_target", "beta_hedge", "ewma_signal"]


def vol_target(weekly: pd.DataFrame, *, ret_col: str = "hl",
               target_ann_vol: float, lookback_weeks: int = 26,
               max_leverage: float = 2.0, min_leverage: float = 0.0,
               turnover_col: str = "turnover", cost_col: str = "cost",
               tc: float = 0.0050) -> pd.DataFrame:
    """Moskowitz-Ooi-Pedersen / Barroso-Santa-Clara ex-ante volatility scaling.

    ``k_t = clip(target / (sd(r_{t-L..t-1}) * sqrt(52)), min_lev, max_lev)``

    The rolling std is **shifted one week**: sizing week t must not see week t's own
    return. Returns the frame with `k`, the scaled return, and a leverage-aware cost.
    """
    d = weekly.sort_values("week").copy()
    r = d[ret_col].astype(float)

    realized = r.rolling(lookback_weeks, min_periods=max(4, lookback_weeks // 2)) \
                .std(ddof=1).shift(1) * np.sqrt(ANN)
    k = (target_ann_vol / realized).clip(lower=min_leverage, upper=max_leverage)
    k = k.fillna(1.0)                      # before the window fills, run unlevered
    d["k"] = k

    # Leverage costs twice: scaled rebalancing, plus rebalancing the leverage itself
    # against the standing book. The second term is what makes k > 1 not free.
    base_turn = d[turnover_col].astype(float) if turnover_col in d else 0.0
    dk = k.diff().abs().fillna(0.0)
    d["cost_vt"] = tc * (k * base_turn + dk * 1.0)
    d[f"{ret_col}_vt"] = k * r
    d[f"{ret_col}_vt_net"] = k * r - d["cost_vt"]
    return d


def beta_hedge(weekly: pd.DataFrame, *, ret_col: str, bench_col: str,
               window_weeks: int = 26, beta_min: float = 0.0,
               beta_max: float = 2.0, funding: pd.Series | None = None,
               credit_funding: bool = True) -> pd.DataFrame:
    """Hedge `ret_col` against `bench_col` with a trailing, strictly causal beta.

    ``r_hedged_t = r_t - beta_{t-1} * bench_t  (- beta_{t-1} * funding_t)``

    `beta_{t-1}` is OLS of r on bench over the `window_weeks` ending at t-1, so no
    part of week t enters the hedge ratio. A short perp position of size beta pays
    `beta * funding` when funding is positive (the short receives it, so the sign
    below subtracts a negative cost). `credit_funding=False` reports the hedge with
    that tailwind withheld.
    """
    d = weekly.sort_values("week").copy()
    r = d[ret_col].astype(float)
    b = d[bench_col].astype(float)

    cov = r.rolling(window_weeks).cov(b)
    var = b.rolling(window_weeks).var(ddof=1)
    beta = (cov / var).shift(1).clip(lower=beta_min, upper=beta_max)
    beta = beta.fillna(0.0)                # unhedged until the window fills
    d["beta"] = beta

    hedged = r - beta * b
    if funding is not None and credit_funding:
        f = d["week"].map(funding).astype(float).fillna(0.0)
        # Short the benchmark => receive funding when the rate is positive.
        d["funding_pnl"] = beta * f
        hedged = hedged + d["funding_pnl"]
    else:
        d["funding_pnl"] = 0.0
    d[f"{ret_col}_hedged"] = hedged
    return d


def ewma_signal(df: pd.DataFrame, *, col: str = "ctrend", halflife_weeks: float,
                week_col: str = "week", id_col: str = "coin_id") -> pd.DataFrame:
    """EWMA-smooth a per-coin signal along a DENSE week axis (U3 lever a).

    Reindexing onto the dense axis first matters: a coin absent for ten weeks must
    not re-enter carrying a ten-week-stale score at full weight, which is what a
    naive groupby-ewm would do.
    """
    if halflife_weeks <= 0:
        return df.copy()
    d = df.sort_values([id_col, week_col]).copy()
    weeks = np.sort(d[week_col].unique())
    out = []
    for cid, g in d.groupby(id_col, sort=False):
        s = g.set_index(week_col)[col].reindex(weeks)
        sm = s.ewm(halflife=halflife_weeks, adjust=False, ignore_na=False).mean()
        keep = sm.reindex(g[week_col].to_numpy())
        gg = g.copy()
        gg[col] = keep.to_numpy()
        out.append(gg)
    return pd.concat(out, ignore_index=True)
