"""Walk-forward accumulator — SPEC §4.3 steps 1-2 and the step-4 pooling.

This object is the one place that sits *outside* the ``Dataset.asof`` contract:
it survives across weeks, so in principle it could carry information backwards.
Three properties close that hole:

1. It stores only **derived** ``(J,)`` coefficient vectors and demeaned design
   blocks — never raw panel data.
2. Every stored array is ``freeze``d, so nothing can be rewritten after the fact.
3. ``ingest`` enforces strictly monotone week advance, so the accumulator cannot
   be fed out of order. Combined with a store that refuses to serve a future
   window, a leak would require reading data that does not exist.

Index convention (identical to the SPEC §5 golden): the pair stored *at* week
``w`` regresses the week-``w`` return on the week-``w-1`` signal. Smoothing over
``[w-M, w-1]`` is therefore **right-exclusive** in golden terms — the pair at
``w``, which embeds ``r_w``, is deliberately excluded.
"""

from __future__ import annotations

import numpy as np

from ctrend.calendar import Week
from ctrend.data.frozen import freeze
from ctrend.data.types import CausalityError, CausalWindow
from ctrend.signal.fm_wls import fm_wls

__all__ = ["WalkForwardState", "PooledBlock"]


class PooledBlock:
    """One week's contribution to the step-4 pooled, demeaned design."""

    __slots__ = ("target", "X", "y", "n")

    def __init__(self, target: Week, X: np.ndarray, y: np.ndarray) -> None:
        self.target = Week(int(target))
        self.X = freeze(X)
        self.y = freeze(y)
        self.n = int(len(y))


class WalkForwardState:
    """Accumulates (alpha_jt, beta_jt) pairs and the pooled combining design."""

    def __init__(self, n_indicators: int, sig_cfg) -> None:
        self.J = int(n_indicators)
        self.cfg = sig_cfg
        self.M = int(sig_cfg.estimation_window_weeks)
        self._alpha: dict[int, np.ndarray] = {}
        self._beta: dict[int, np.ndarray] = {}
        self._pool: list[PooledBlock] = []
        self._high_water: int | None = None
        self.skipped: dict[int, str] = {}

    # -- ingestion ----------------------------------------------------------
    def ingest(self, win: CausalWindow) -> None:
        """Consume the window for week ``win.week``: one WLS pair, one pool block."""
        week = int(win.week)
        if self._high_water is not None and week <= self._high_water:
            raise CausalityError(
                f"week {week} <= high water {self._high_water}: the walk-forward "
                "accumulator only advances"
            )
        if len(win.weeks) < 2:
            self._high_water = week
            self.skipped[week] = "no t-1 row in window"
            return

        prev, cur = win.at(-1), win.at(0)
        # nan_policy: inner_join — a coin must be eligible at BOTH t-1 and t.
        # Compaction, not zero-weight padding: padding perturbs the np.sum
        # reductions below at ~1e-15 and would silently break bit-identity.
        mask = prev.eligible & cur.eligible
        z_all, r_all, mc_all = prev.signals, cur.excess_returns, prev.market_cap
        mask &= np.isfinite(r_all) & np.isfinite(mc_all) & (mc_all > 0)
        mask &= np.isfinite(z_all).all(axis=1)

        n = int(mask.sum())
        if n < int(self.cfg.min_cross_section):
            self._high_water = week
            self.skipped[week] = f"cross-section {n} < min {self.cfg.min_cross_section}"
            return

        z = np.ascontiguousarray(z_all[mask])
        r = np.ascontiguousarray(r_all[mask])
        mc = np.ascontiguousarray(mc_all[mask])

        # Pool block for target week `week` uses pairs strictly older than `week`.
        if self.has_smoothed(Week(week)):
            ab, bb = self.smoothed(Week(week))
            f = ab + z * bb
            self._pool.append(
                PooledBlock(Week(week), f - f.mean(0), r - r.mean())
            )

        alpha, beta = fm_wls(
            z, r, mc,
            var_floor=float(self.cfg.var_floor),
            normalize=bool(self.cfg.wls_weights_normalize),
        )
        self._alpha[week] = freeze(alpha)
        self._beta[week] = freeze(beta)
        self._high_water = week

    # -- SPEC §4.3 step 2 ---------------------------------------------------
    def has_smoothed(self, target: Week) -> bool:
        lo = int(target) - self.M
        return lo >= 0 and all(w in self._alpha for w in range(lo, int(target)))

    def smoothed(self, target: Week) -> tuple[np.ndarray, np.ndarray]:
        """Trailing means of (alpha, beta) over pair weeks ``[target-M, target-1]``."""
        lo = int(target) - self.M
        if not self.has_smoothed(target):
            raise CausalityError(f"smoothed({target}) needs pairs {lo}..{int(target) - 1}")
        idx = range(lo, int(target))
        a = np.mean([self._alpha[w] for w in idx], axis=0)
        b = np.mean([self._beta[w] for w in idx], axis=0)
        return a, b

    # -- SPEC §4.3 step 4 pooling ------------------------------------------
    def pool_size(self, week: Week) -> int:
        return sum(1 for b in self._pool if b.target <= int(week))

    def pooled(self, week: Week) -> tuple[np.ndarray, np.ndarray]:
        """Pooled, demeaned design over combining targets ``<= week``.

        ``training_window: expanding`` — targets [53, t]. A rolling variant would
        slice ``self._pool`` here; §4.3 step 4 never defines the window, so the
        expanding reading is used and logged in DECISIONS.md.
        """
        blocks = [b for b in self._pool if b.target <= int(week)]
        if not blocks:
            raise CausalityError(f"combining pool is empty at week {week}")
        X = np.vstack([b.X for b in blocks])
        y = np.concatenate([b.y for b in blocks])
        return X, y

    @property
    def high_water(self) -> int | None:
        return self._high_water
