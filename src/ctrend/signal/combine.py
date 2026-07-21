"""SPEC §4.3 step 4 — the ElasticNet combining step with AICc lambda selection.

Reconciled against the authors' code 2026-07-18 (GT-9, GT-10, GT-11).

`fWalkforwardCSENET.m:196-197` calls `fEstRegPanelRegression`, which at `:50`
defaults `iNumLambda = 200` and at `:82-94` hands it to MATLAB `lasso` with
`Standardize = true` and the supplied market-cap `Weights`. MATLAB's grid is
**data-dependent**: geometric from `lambda_max` — the smallest λ that zeroes every
coefficient — down to `LambdaRatio * lambda_max` (default 1e-4), recomputed for
every rolling window. Our earlier reading (25 fixed points on [1e-4, 1]) selects a
different indicator set roughly half the time; see DECISIONS.md GT-9 for the
measurement, including the correction to an overstated severity claim.

AICc, `fEstRegPanelRegression.m:108`:

    vAIC = n * log(MSE) + 2 * DF * n / (n - DF - 1)

`DF` is the count of nonzero coefficients **excluding the intercept**. Our
`2k + 2k(k+1)/(n-k-1)` factorizes to `2k*n/(n-k-1)` and is algebraically identical,
so only `k` differed: the authors use `k = nonzero`, not `nonzero + 1` (GT-10).

INVARIANT I2. This module must never import ``sklearn.model_selection``. Lambda is
chosen by in-sample AICc and by nothing else. The strict ``<`` comparison makes ties
favour the first grid point; the grid is ordered high→low for the data-dependent
mode (as MATLAB emits it) and low→high for the superseded fixed mode, so in both
cases ties resolve toward the **sparser** model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import ElasticNet, enet_path

__all__ = ["CombinerFit", "lambda_grid", "lambda_max", "fit_combiner"]


@dataclass(frozen=True, slots=True)
class CombinerFit:
    theta: np.ndarray  # (J,) combining coefficients, on the ORIGINAL X scale
    lam: float
    aicc: float
    intercept: float
    n_pooled: int


def lambda_max(X: np.ndarray, y: np.ndarray, l1_ratio: float) -> float:
    """Smallest lambda that zeroes every coefficient.

    sklearn's objective is ``1/(2n)||y - Xw||^2 + alpha*l1_ratio*||w||_1 + ...``,
    the same parametrization MATLAB `lasso` uses, so the closed form is
    ``max|X'y| / (n * l1_ratio)`` on the centred/standardized design.
    """
    n = len(y)
    return float(np.abs(X.T @ y).max() / (n * l1_ratio))


def lambda_grid(cfg, X: np.ndarray | None = None, y: np.ndarray | None = None) -> np.ndarray:
    """GT-9: data-dependent by default; the fixed grid is a sensitivity axis."""
    g = cfg.lambda_grid
    mode = getattr(g, "mode", "fixed")
    if mode == "data_dependent":
        if X is None or y is None:
            raise ValueError("data_dependent lambda grid needs the design matrix")
        lmax = lambda_max(X, y, cfg.l1_ratio)
        if not np.isfinite(lmax) or lmax <= 0:
            raise ValueError(f"degenerate lambda_max={lmax!r}")
        # High -> low, as MATLAB emits it.
        return np.geomspace(lmax, g.ratio * lmax, g.n)
    if g.log_low is None or g.log_high is None:
        raise ValueError("fixed lambda grid requires log_low and log_high")
    return np.logspace(g.log_low, g.log_high, g.n)


def fit_combiner(X: np.ndarray, y: np.ndarray, cfg) -> CombinerFit:
    """Fit the combining ElasticNet and select lambda by corrected AIC."""
    if cfg.selection != "aicc":  # belt and braces; config.py already rejects this
        raise ValueError("I2: only AICc lambda selection is permitted")
    n = len(y)

    # MATLAB lasso standardizes X internally and returns coefficients on the
    # original scale. sklearn dropped `normalize`, so do it explicitly and undo it
    # at the end. Selection is unaffected either way -- rescaling by a positive
    # sigma preserves sign, hence the theta > 0 rule -- but downstream forecasts
    # are formed on the original scale.
    if getattr(cfg, "standardize", True):
        sigma = X.std(axis=0, ddof=0)
        sigma = np.where(sigma > 0, sigma, 1.0)
        Xf = (X - X.mean(axis=0)) / sigma
    else:
        sigma = np.ones(X.shape[1])
        Xf = X

    use_k_plus_one = getattr(cfg, "aicc_k", "nonzero") != "nonzero"
    grid = lambda_grid(cfg, Xf, y)

    # Solve the whole lambda path with warm starts rather than fitting each lambda
    # from cold. This is not merely an optimisation:
    #
    #   * MATLAB `lasso` -- the authors' estimator -- computes the path with warm
    #     starts (glmnet-style), so the path solver is the *more* faithful port.
    #   * The design is 28 near-collinear forecast columns (condition number ~470).
    #     Cold-started coordinate descent at small lambda does not converge inside
    #     `max_iter`: measured at ~7.1 s per fit and still short of the optimum,
    #     against 0.67 s for the entire 200-point path. The cold fits were both
    #     ~750x slower AND further from the solution.
    #
    # `enet_path` fits no intercept, so centre here and recover it afterwards.
    #
    # The path MUST be traversed high -> low lambda: each solve is warm-started from
    # the previous one, and the sequence only makes sense walking from the all-zero
    # end toward denser solutions. `enet_path` consumes `alphas` in the order given,
    # so an ascending grid (the superseded fixed mode is `logspace(-4, 0)`) would
    # warm-start backwards and land on different coefficients. Sort descending here
    # and restore the caller's order afterwards.
    x_mean, y_mean = Xf.mean(axis=0), float(y.mean())
    order = np.argsort(-np.asarray(grid, dtype="float64"))
    _, coefs_desc, _ = enet_path(
        Xf - x_mean, y - y_mean,
        l1_ratio=cfg.l1_ratio,
        alphas=np.asarray(grid, dtype="float64")[order],
        max_iter=cfg.max_iter,
    )
    coefs = np.empty_like(coefs_desc)
    coefs[:, order] = coefs_desc

    best: CombinerFit | None = None
    for i, lam in enumerate(grid):
        w = coefs[:, i]
        k = int((w != 0).sum()) + (1 if use_k_plus_one else 0)  # GT-10
        if k >= n - 1:  # AICc penalty is undefined/negative past this point
            continue
        resid = (y - y_mean) - (Xf - x_mean) @ w
        sse = float(resid @ resid)
        if sse <= 0:
            continue
        aicc = n * np.log(sse / n) + 2 * k * n / (n - k - 1)
        if best is None or aicc < best.aicc:  # strict: ties favour the sparser fit
            best = CombinerFit(
                theta=w / sigma,  # back to the original X scale
                lam=float(lam),
                aicc=float(aicc),
                intercept=float(y_mean - x_mean @ w),
                n_pooled=n,
            )
    if best is None:
        raise ValueError(f"no admissible lambda on the grid (n={n})")
    return best
