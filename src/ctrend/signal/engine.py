"""CS-C-ENet walk-forward driver — SPEC §4.3 steps 3 and 5.

    step 3: "Per-indicator forecast for *t+1*: smoothed alpha + smoothed beta x
             signal at *t*."
    step 5: "CTREND for *t+1* = equal-weighted mean of the per-indicator
             forecasts whose combining coefficient theta_j > 0. Every quantity at
             *t* uses data <= *t* only."

``Dataset.asof`` is the only data access in this module — that is invariant I1
made structural rather than aspirational.

Alignment note (``signal.forecast_alignment: t_plus_1``, logged in DECISIONS.md).
The SPEC §5 golden indexes every quantity by the week whose return it explains:
its "forecast at t" uses ``Z[t-1]`` and pairs ``[t-M, t-1]``. That convention is
correct for the *training* design, and this engine reproduces it exactly there
(see :mod:`ctrend.signal.state`). For the value actually **emitted**, §4.3 step 3
is taken literally: the forecast for *t+1* uses the signal at *t* and pairs
``[t+1-M, t]``, all of which are known at *t*. Labelling the golden's fit-for-*t*
as a forecast for *t+1* would be an off-by-one that reads as look-ahead the
moment M4 accounts for it. The choice also lands the first emission exactly where
SPEC §6 M3 says it should: with M = 52 the earliest full smoothing window closes
at *t* = 52. Under GT-8 ``smoothing: window_mean`` the in-sample block is the M
weeks ending at the signal week, so the first ENet-combined CTREND is for week
53 -- exactly where SPEC §6 M3 says it should be, and where the authors' own
first forecast lands (201416 + 52 = 201516).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd

from ctrend import J_INDICATORS
from ctrend.calendar import Week
from ctrend.data.dataset import Dataset
from ctrend.data.types import TruncationBounds
from ctrend.signal.combine import CombinerFit, fit_combiner
from ctrend.signal.state import WalkForwardState

__all__ = ["CtrendWeek", "run", "ctrend_at", "ctrend_frame"]


@dataclass(frozen=True, slots=True)
class CtrendWeek:
    """CTREND for ``target_week``, produced using data <= ``signal_week``."""

    target_week: Week
    signal_week: Week
    coins: np.ndarray
    values: np.ndarray
    selected: np.ndarray
    theta: np.ndarray
    lam: float
    aicc: float
    n_pooled: int
    truncation: TruncationBounds
    #: U5 selection stability. `values_by_level[:, i]` is CTREND under the rule
    #: "an indicator counts only if theta>0 in ALL of the last levels[i] windows".
    #: levels[0] is always 1, so `values` and column 0 coincide and every existing
    #: caller and pinned test is unaffected.
    levels: tuple[int, ...] = (1,)
    values_by_level: np.ndarray | None = None
    n_selected_by_level: tuple[int, ...] = ()

    @property
    def index(self) -> pd.Index:
        return pd.Index(self.coins, name="coin_id")

    @property
    def series(self) -> pd.Series:
        return pd.Series(self.values, index=self.index, name=f"ctrend_w{self.target_week}")

    @property
    def is_empty_selection(self) -> bool:
        return self.selected.size == 0


def run(ds: Dataset, cfg, *, through: Week | None = None,
        stability_levels: tuple[int, ...] = (1,)) -> Iterator[CtrendWeek]:
    """Yield one :class:`CtrendWeek` per week for which CTREND is defined.

    `stability_levels` (U5) evaluates several persistence rules in ONE pass: an
    indicator enters the combined forecast only if theta_j > 0 in all of the last N
    fitted windows. Computing every N together avoids one full walk-forward per N,
    which is the single most expensive stage. Level 1 is the unmodified rule.
    """
    sig = cfg.signal
    state = WalkForwardState(J_INDICATORS, sig)
    last = int(through) if through is not None else int(ds.calendar.last_week)
    levels = tuple(sorted(set((1,) + tuple(stability_levels))))
    history: list[np.ndarray] = []   # boolean theta>0 masks, most recent last

    for week in ds.calendar.iter_weeks():
        if int(week) > last:
            break
        # THE ONLY data access in src/ctrend/signal (invariant I1).
        win = ds.asof(week, lookback=1)
        state.ingest(win)

        target = Week(int(week) + 1)
        if not state.has_smoothed(target):
            continue
        if state.pool_size(week) < int(sig.min_pool_weeks):
            continue

        X, y = state.pooled(week)
        fit: CombinerFit = fit_combiner(X, y, sig.elasticnet)

        ab, bb = state.smoothed(target)
        cur = win.at(0)
        mask = cur.eligible & np.isfinite(cur.signals).all(axis=1)
        z = np.ascontiguousarray(cur.signals[mask])
        coins = np.ascontiguousarray(win.coins[mask])

        pos = fit.theta > 0
        history.append(pos)
        if len(history) > max(levels):
            history.pop(0)

        sel = np.where(pos)[0]  # STRICTLY positive: zeros and negatives dropped
        if sel.size == 0:
            # empty_selection: nan — the golden's mean over an empty axis is NaN
            # and is left unguarded there; here it is explicit and logged.
            values = np.full(len(coins), np.nan)
        else:
            values = (ab + z * bb)[:, sel].mean(1)

        # U5: an indicator survives level N only if positive in the last N windows.
        forecasts = ab + z * bb
        by_level = np.full((len(coins), len(levels)), np.nan)
        n_by_level = []
        for i, n in enumerate(levels):
            if len(history) < n:
                n_by_level.append(0)
                continue
            stable = np.logical_and.reduce(history[-n:])
            idx = np.where(stable)[0]
            n_by_level.append(int(idx.size))
            if idx.size:
                by_level[:, i] = forecasts[:, idx].mean(1)

        yield CtrendWeek(
            target_week=target,
            signal_week=Week(int(week)),
            coins=coins,
            values=values,
            selected=sel,
            theta=fit.theta,
            lam=fit.lam,
            aicc=fit.aicc,
            n_pooled=fit.n_pooled,
            truncation=win.truncation,
            levels=levels,
            values_by_level=by_level,
            n_selected_by_level=tuple(n_by_level),
        )


def ctrend_at(ds: Dataset, cfg, week: Week) -> CtrendWeek:
    """Drive :func:`run` up to signal week ``week`` and return that result."""
    out = None
    for cw in run(ds, cfg, through=week):
        out = cw
    if out is None or int(out.signal_week) != int(week):
        raise ValueError(f"CTREND is not defined at signal week {week}")
    return out


def ctrend_frame(ds: Dataset, cfg, *, through: Week | None = None) -> pd.DataFrame:
    """All CTREND values as a tidy frame (target_week, coin_id, ctrend)."""
    rows = [
        pd.DataFrame(
            {
                "target_week": int(cw.target_week),
                "coin_id": cw.coins,
                "ctrend": cw.values,
            }
        )
        for cw in run(ds, cfg, through=through)
    ]
    if not rows:
        return pd.DataFrame(columns=["target_week", "coin_id", "ctrend"])
    return pd.concat(rows, ignore_index=True)
