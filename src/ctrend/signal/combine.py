"""SPEC §4.3 step 4 — the ElasticNet combining step with AICc lambda selection.

    "pool weeks; cross-sectionally demean both realized returns and each of the
     J = 28 forecasts (time fixed effects); fit ElasticNet with l1_ratio=0.5 over
     a log-spaced lambda grid (25 points, 1e-4 to 1); choose lambda by corrected
     AIC with k = (nonzero coefficients + 1) and n = pooled observations:
     AICc = n*ln(SSE/n) + 2k + 2k(k+1)/(n-k-1).
     **Cross-validation is prohibited here (I2).**"

INVARIANT I2. This module must never import ``sklearn.model_selection``. Lambda
is chosen by in-sample AICc over the fixed grid and by nothing else. The strict
``<`` comparison makes ties favour the *first*, i.e. smallest, lambda — matching
the golden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import ElasticNet

__all__ = ["CombinerFit", "lambda_grid", "fit_combiner"]


@dataclass(frozen=True, slots=True)
class CombinerFit:
    theta: np.ndarray  # (J,) combining coefficients
    lam: float
    aicc: float
    intercept: float
    n_pooled: int


def lambda_grid(cfg) -> np.ndarray:
    """``np.logspace(-4, 0, 25)`` under the paper defaults."""
    g = cfg.lambda_grid
    return np.logspace(g.log_low, g.log_high, g.n)


def fit_combiner(X: np.ndarray, y: np.ndarray, cfg) -> CombinerFit:
    """Fit the combining ElasticNet and select lambda by corrected AIC."""
    if cfg.selection != "aicc":  # belt and braces; config.py already rejects this
        raise ValueError("I2: only AICc lambda selection is permitted")
    n = len(y)
    best: CombinerFit | None = None
    for lam in lambda_grid(cfg):
        en = ElasticNet(alpha=float(lam), l1_ratio=cfg.l1_ratio, max_iter=cfg.max_iter).fit(X, y)
        k = int((en.coef_ != 0).sum()) + 1
        sse = float(((y - en.predict(X)) ** 2).sum())
        aicc = n * np.log(sse / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1)
        if best is None or aicc < best.aicc:  # strict: ties keep the smallest lambda
            best = CombinerFit(
                theta=en.coef_.copy(),
                lam=float(lam),
                aicc=float(aicc),
                intercept=float(en.intercept_),
                n_pooled=n,
            )
    assert best is not None
    return best
