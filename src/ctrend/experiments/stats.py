"""Multiple-testing treatment for ~10 configurations on 133 weeks.

With this family size roughly one configuration clears t > 2 by chance, so a table of
raw t-statistics would be actively misleading. Five columns are reported for every
configuration — never a subset, which `report_table` enforces by raising.

The primary statistic is the PAIRED difference `d_t = r_k,t - r_0,t`, not the level.
Levels on 133 weeks have a minimum detectable effect near 1.6%/wk against a 0.52%/wk
baseline, i.e. no upgrade could ever be declared. Overlays share the same underlying
signal, so the difference series has far smaller dispersion and is the only statistic
with usable power here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

ANN = 52.0


def paired_t(diff: pd.Series) -> tuple[float, float]:
    """One-sided t and p for H0: E[d] <= 0."""
    d = diff.dropna().astype(float)
    n = len(d)
    if n < 5 or d.std(ddof=1) == 0:
        return np.nan, np.nan
    t = d.mean() / (d.std(ddof=1) / np.sqrt(n))
    return float(t), float(1 - stats.t.cdf(t, df=n - 1))


def benjamini_hochberg(p: np.ndarray, q: float = 0.10) -> np.ndarray:
    """BH adjusted q-values. Valid under positive dependence (PRDS), which nested
    configurations sharing one signal plausibly satisfy — and far less brutal than
    Bonferroni at family size 10."""
    p = np.asarray(p, dtype=float)
    ok = ~np.isnan(p)
    out = np.full(p.shape, np.nan)
    m = ok.sum()
    if m == 0:
        return out
    idx = np.argsort(np.where(ok, p, np.inf))[:m]
    adj = np.empty(m)
    running = 1.0
    for rank in range(m - 1, -1, -1):
        val = p[idx[rank]] * m / (rank + 1)
        running = min(running, val)
        adj[rank] = running
    out[idx] = np.clip(adj, 0, 1)
    return out


def haircut_sharpe(sr: float, t: float, p_adj: float) -> float:
    """Harvey-Liu-Zhu: rescale the Sharpe by the ratio of the multiple-testing
    adjusted t to the observed t.

    `sr` and `t` must describe the SAME quantity. Passing a level Sharpe with a
    paired-difference t (as this was originally called) is not the HLZ procedure and
    silently rescales one statistic by another's significance.

    The clip at ``1 - 1e-12`` saturates: any ``p_adj`` at or above 1 gives
    ``t_adj = 0`` and therefore a haircut of exactly 0 for ANY Sharpe, however large.
    That is arithmetically correct but carries no information about the strategy —
    it only says the adjusted p-value hit the ceiling. Callers must not report a
    zero here as evidence about the Sharpe itself.
    """
    if not np.isfinite(sr) or not np.isfinite(t) or t <= 0 or not np.isfinite(p_adj):
        return np.nan
    p_adj = min(max(p_adj, 1e-12), 1 - 1e-12)
    t_adj = stats.norm.ppf(1 - p_adj / 2)
    return float(sr * max(t_adj, 0.0) / t)


def spa_pvalue(diffs: pd.DataFrame, n_boot: int = 5000, block: float = 4.0,
               seed: int = 20260720) -> float:
    """Stationary-bootstrap SPA (White 2000 / Hansen 2005).

    The only statistic here that handles dependence BETWEEN configurations. Tests
    'the best configuration genuinely beats the baseline' against the null that none
    does, resampling the whole matrix jointly with expected block length `block`
    weeks to preserve autocorrelation.
    """
    d = diffs.dropna(how="any")
    if d.empty or len(d) < 20:
        return np.nan
    x = d.to_numpy(dtype=float)
    # Drop degenerate columns BEFORE anything else. A bit-exact no-op configuration has
    # sd at machine-epsilon scale rather than exactly 0, so an `sd == 0` test never fires
    # and its rounding residue — which has no economic content whatsoever — competes for
    # the family maximum. Guarding only the observed statistic is not enough: the same
    # column is resampled `n_boot` times inside the loop below and can take the maximum
    # there too, which shifts the p-value without touching t_obs.
    scale = max(float(np.abs(x).max()), 1.0)
    keep = x.std(0, ddof=1) > 1e-12 * scale
    if not keep.any():
        return np.nan
    x = x[:, keep]
    n, k = x.shape
    mu = x.mean(0)
    sd = x.std(0, ddof=1)
    t_obs = float(np.max(np.sqrt(n) * mu / sd))

    rng = np.random.default_rng(seed)
    p_geom = 1.0 / block
    centred = x - mu                      # impose the null
    count = 0
    for _ in range(n_boot):
        idx = np.empty(n, dtype=int)
        i = rng.integers(0, n)
        for j in range(n):
            if j > 0 and rng.random() < p_geom:
                i = rng.integers(0, n)
            idx[j] = i
            i = (i + 1) % n
        b = centred[idx]
        bm, bs = b.mean(0), b.std(0, ddof=1)
        bs[bs == 0] = np.inf
        if float(np.max(np.sqrt(n) * bm / bs)) >= t_obs:
            count += 1
    return (count + 1) / (n_boot + 1)


def report_table(series: dict[str, pd.Series], baseline: str,
                 expected: set[str] | None = None) -> pd.DataFrame:
    """Full results table. Raises if any expected configuration is missing —
    there is deliberately no code path that emits a subset."""
    if expected and set(series) != set(expected):
        missing = set(expected) - set(series)
        extra = set(series) - set(expected)
        raise ValueError(f"incomplete report: missing={sorted(missing)} extra={sorted(extra)}")
    base = series[baseline].dropna()
    rows, diffs = [], {}
    for name, s in series.items():
        s = s.dropna()
        common = base.index.intersection(s.index)
        d = (s.loc[common] - base.loc[common]) if name != baseline else pd.Series(0.0, index=common)
        diffs[name] = d
        mu, sd = s.mean(), s.std(ddof=1)
        sr = mu / sd * np.sqrt(ANN) if sd > 0 else np.nan
        t, p = paired_t(d) if name != baseline else (np.nan, np.nan)
        # The haircut must rescale the Sharpe of the quantity actually tested — the
        # paired difference — not the level Sharpe, which no test in this table bears on.
        dsd = d.std(ddof=1)
        dsr = (d.mean() / dsd * np.sqrt(ANN)) if (name != baseline and dsd > 0) else np.nan
        eq = (1 + s).cumprod()
        rows.append({"config": name, "n": len(s), "mean_pct": mu * 100,
                     "sd_pct": sd * 100, "sharpe": sr,
                     "max_dd_pct": float((eq / eq.cummax() - 1).min() * 100),
                     "hit_pct": float((s > 0).mean() * 100),
                     "diff_mean_pct": float(d.mean() * 100),
                     "diff_sharpe": dsr, "t_paired": t, "p_raw": p})
    out = pd.DataFrame(rows)
    out["q_BH"] = benjamini_hochberg(out["p_raw"].to_numpy())
    # Tests actually performed. A degenerate configuration yields no p-value and must
    # not inflate M — the baseline never did, and neither does a bit-exact no-op.
    n_tests = int(out["p_raw"].notna().sum())
    out["bonferroni_pass"] = out["p_raw"] < (0.05 / max(n_tests, 1))
    for M, lab in ((n_tests, f"M{n_tests}"), (31, "M31"), (316, "M316")):
        out[f"diff_sr_haircut_{lab}"] = [
            haircut_sharpe(r.diff_sharpe, r.t_paired, min(1.0, (r.p_raw or 1) * M))
            if np.isfinite(r.t_paired) else np.nan for r in out.itertuples()]
    dd = pd.DataFrame({k: v for k, v in diffs.items() if k != baseline})
    out.attrs["spa_p"] = spa_pvalue(dd)
    return out
