"""Golden test: CS-C-ENet miniature. Expected selection: exactly {0, 3, 7, 12, 20}.

READ-ONLY (SPEC.md §5). Any refactor of src/ctrend/signal/ must keep this green
with its assertions unchanged. Widening or editing the assertions violates I3.

Verified 2026-07-18 on numpy 2.x / scikit-learn 1.9.0: selection reproduces
exactly, holdout IC = 0.088, lambda = 0.004642. Seven coefficients are nonzero
but only five are positive -- indices 22 and 27 carry negative theta and are
correctly excluded by the theta_j > 0 rule, while planted index 7 (true loading
-0.5) survives because its univariate forecast flips sign through beta.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
from sklearn.linear_model import ElasticNet
from scipy.stats import spearmanr


def test_cenet_golden():
    rng = np.random.default_rng(7)
    N, T, J, M = 250, 90, 28, 52
    true_b = np.zeros(J); true_b[[0, 3, 7, 12, 20]] = [0.9, 0.7, -0.5, 0.6, 0.4]
    Z = rng.uniform(-0.5, 0.5, (T, N, J))                      # rank-mapped signals
    R = np.zeros((T, N))
    for t in range(1, T):
        R[t] = Z[t - 1] @ true_b + rng.normal(0, 3, N)          # r_t depends on z_{t-1}
    mcap = rng.lognormal(3, 1, N); w = mcap / mcap.sum()

    alph, bet = np.zeros((T, J)), np.zeros((T, J))
    for t in range(1, T):                                       # 28 univariate WLS FM regressions
        z, r = Z[t - 1], R[t]
        zm, rm = w @ z, w @ r
        var = (w[:, None] * (z - zm) ** 2).sum(0)
        bet[t] = (w[:, None] * (z - zm) * (r - rm)[:, None]).sum(0) / np.maximum(var, 1e-12)
        alph[t] = rm - bet[t] * zm

    X_list, y_list = [], []
    for t in range(M + 1, T - 1):                               # pooled, demeaned training set
        ab, bb = alph[t - M:t].mean(0), bet[t - M:t].mean(0)    # 52-week smoothing, data <= t-1
        f = ab + Z[t - 1] * bb
        X_list.append(f - f.mean(0)); y_list.append(R[t] - R[t].mean())
    X, y = np.vstack(X_list), np.concatenate(y_list)

    best = None                                                 # custom AICc over lambda grid
    for lam in np.logspace(-4, 0, 25):
        en = ElasticNet(alpha=lam, l1_ratio=0.5, max_iter=20000).fit(X, y)
        k = int((en.coef_ != 0).sum()) + 1; n = len(y)
        sse = float(((y - en.predict(X)) ** 2).sum())
        aicc = n * np.log(sse / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1)
        if best is None or aicc < best[0]:
            best = (aicc, lam, en.coef_.copy())
    sel = np.where(best[2] > 0)[0]

    t = T - 1                                                   # holdout week
    ab, bb = alph[t - M:t].mean(0), bet[t - M:t].mean(0)
    ctrend = (ab + Z[t - 1] * bb)[:, sel].mean(1)
    ic = spearmanr(ctrend, R[t])[0]

    assert set(sel.tolist()) == {0, 3, 7, 12, 20}, f"selection drifted: {sel.tolist()}"
    assert ic > 0, f"holdout IC not positive: {ic}"
    print(f"GOLDEN PASS | selected={sel.tolist()} | holdout IC={ic:.3f}")
