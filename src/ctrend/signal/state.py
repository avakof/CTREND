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

GT-8 — two smoothing regimes, and why the pool is built differently under each
-----------------------------------------------------------------------------
``fEstFamaMacBethPanel.m:156-157`` collapses the window's weekly gammas to **one**
``(alpha_bar, beta_bar)`` pair, and ``fPredictFamaMacBethPanel.m:67`` applies that
single pair to *every* in-sample week as well as to the out-of-sample week. Our
earlier reading — a trailing mean recomputed per target week, giving each pooled
row its own pair — is the SPEC §5 golden's algorithm, not the authors'.

The pair itself is computed identically in both regimes (the mean of the gammas
over ``[tau-M, tau-1]``). What differs is **application**, and that changes the
data structure:

* ``trailing_mean`` — each target week's block is formed once, at ingest, from that
  week's own smoothed pair. The pool accumulates incrementally.
* ``window_mean`` (GT-8, default) — the pair belongs to the *forecast iteration*,
  so it applies retroactively to all 52 training weeks. The design therefore
  cannot be accumulated; it is **rebuilt at each forecast week**.

Rebuilding needs the per-week ``(z_{s-1}, r_s)`` arrays, so ``window_mean`` retains
them. That is bounded and strictly historical: at most ``M + 1`` weeks are kept,
every one already ingested, and eviction is driven by the high-water mark rather
than by any future week. The causality argument in the list above is unaffected.
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
        # GT-8 window_mean only: per-week (z_{s-1}, r_s), needed to rebuild the
        # design when the iteration's single pair changes. Bounded to M+1 weeks.
        self._obs: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._high_water: int | None = None
        self.skipped: dict[int, str] = {}

    # -- GT-8 regime --------------------------------------------------------
    @property
    def smoothing(self) -> str:
        return getattr(self.cfg, "smoothing", "window_mean")

    def _window_lo(self, week: int) -> int:
        """First training target for forecast ``week``.

        ``training_window: rolling:N`` -> [week-N, week-1] (the authors: lRoll=true,
        iNumIn=52). ``expanding`` -> everything available. GT-8.
        """
        spec = str(getattr(self.cfg, "training_window", "rolling:52"))
        if spec.startswith("rolling:"):
            return int(week) - int(spec.split(":", 1)[1])
        return 0

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

        if self.smoothing == "window_mean":
            # GT-8: the design is rebuilt per forecast week, so keep the raw
            # (z_{t-1}, r_t) rather than a block frozen against one pair. Evict
            # anything older than the widest window we could still be asked for.
            self._obs[week] = (freeze(z), freeze(r))
            if str(getattr(self.cfg, "training_window", "rolling:52")).startswith("rolling:"):
                cutoff = week - self.M - 1
                for stale in [w for w in self._obs if w < cutoff]:
                    del self._obs[stale]
        elif self.has_smoothed(Week(week)):
            # trailing_mean: block for target `week` uses pairs strictly older
            # than `week`, frozen at ingest.
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
    def training_targets(self, week: Week) -> list[int]:
        """Target weeks entering the combining design at signal week ``week``.

        Under ``window_mean`` the emission at signal week ``w`` forecasts target
        ``w+1``, and ``fWalkforwardCSENET.m:100-108`` sets the in-sample block to
        the ``M`` weeks **ending at** ``w``. In this module's right-exclusive
        convention that is ``[w+1-M, w]`` — precisely the span whose gammas
        ``smoothed(w+1)`` averages, so the design and the out-of-sample forecast
        are driven by the *same* pair, as ``fPredictFamaMacBethPanel.m:67`` requires.
        """
        if self.smoothing == "window_mean":
            target = int(week) + 1
            lo = self._window_lo(target)
            return sorted(s for s in self._obs if lo <= s <= int(week))
        lo = self._window_lo(int(week))
        return sorted(b.target for b in self._pool if lo <= b.target <= int(week))

    def pool_size(self, week: Week) -> int:
        return len(self.training_targets(week))

    def pooled(self, week: Week) -> tuple[np.ndarray, np.ndarray]:
        """Pooled, cross-sectionally demeaned combining design (SPEC §4.3 step 4).

        GT-11: only the **returns** are demeaned here, equal-weighted. The forecasts
        are not — the combining step fits one global intercept and carries no time
        fixed effects. Both regimes below preserve that.

        GT-8 ``window_mean``: one ``(alpha_bar, beta_bar)`` for the whole iteration,
        applied to every training week's signal row. ``trailing_mean``: each block
        already carries its own pair, frozen at ingest.
        """
        targets = self.training_targets(week)
        if not targets:
            raise CausalityError(f"combining pool is empty at week {week}")

        if self.smoothing != "window_mean":
            blocks = [b for b in self._pool if b.target in set(targets)]
            X = np.vstack([b.X for b in blocks])
            y = np.concatenate([b.y for b in blocks])
            return X, y

        # Same pair the engine will use to emit the forecast for week+1.
        ab, bb = self.smoothed(Week(int(week) + 1))
        Xs, ys = [], []
        for s in targets:
            z, r = self._obs[s]
            f = ab + z * bb
            Xs.append(f - f.mean(0))
            ys.append(r - r.mean())
        return np.vstack(Xs), np.concatenate(ys)

    @property
    def high_water(self) -> int | None:
        return self._high_water
