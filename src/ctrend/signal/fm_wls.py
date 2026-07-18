"""SPEC §4.3 step 1 — weekly univariate cross-sectional WLS (Fama-MacBeth style).

    "Each week *t*, for each indicator *j*: univariate cross-sectional WLS
     regression of week-*t* excess returns on the rank-mapped signal observed at
     *t-1*; regression weights = market cap. Store the pair (alpha_jt, beta_jt)."

The closed form mirrors the SPEC §5 golden exactly, including the degenerate
variance guard. Two resolutions that the golden's time-invariant weight vector
cannot arbitrate are made explicit here and logged in DECISIONS.md:

* ``wls_weights_normalize: true`` — ``w = mcap / mcap.sum()``. Beta is invariant
  to the scaling of the weights; **alpha is not**, because ``zm``/``rm`` are only
  means when the weights sum to one.
* ``wls_weight_date: signal`` — the market cap used is the one observed at the
  signal date *t-1*, the conservative reading under invariant I1.
"""

from __future__ import annotations

import numpy as np

__all__ = ["fm_wls"]


def fm_wls(
    z: np.ndarray, r: np.ndarray, mcap: np.ndarray, *, var_floor: float = 1e-12,
    normalize: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(alpha, beta)``, each shape ``(J,)``.

    Parameters
    ----------
    z : (N, J) rank-mapped signals observed at *t-1*, in [-0.5, +0.5].
    r : (N,)   excess returns realized at *t* (already truncated, A5).
    mcap : (N,) market caps used as regression weights.
    """
    w = mcap / mcap.sum() if normalize else mcap
    zm = w @ z
    rm = w @ r
    var = (w[:, None] * (z - zm) ** 2).sum(0)
    beta = (w[:, None] * (z - zm) * (r - rm)[:, None]).sum(0) / np.maximum(var, var_floor)
    alpha = rm - beta * zm
    return alpha, beta
