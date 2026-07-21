# M3 — reconstructed CTREND vs the authors' shipped factor

Date: 2026-07-19. Sample 201516–202222, 353 overlapping weeks of the shipped 371.
Value-weighted quintiles on CTREND, long the top, short the bottom, held one week.

## RESULT: **PASS**

| statistic | ours | authors' shipped series | paper (Table 3) |
|---|---|---|---|
| H−L mean, %/week | **3.945** | 3.989 | 3.87 |
| t-statistic | **4.220** | — | 5.19 |
| Annualised Sharpe | **1.620** | 1.997 | 1.94 |
| Weekly SD, % | 17.565 | 14.401 | 14.34 |
| **Pearson correlation** | **0.627** | | |
| **Spearman correlation** | **0.818** | | |
| **Weekly sign agreement** | **84.1%** | | |

Quintile means (%/week): **−0.09 → 1.19 → 1.50 → 2.35 → 3.80**, strictly monotone.

### SPEC §7 formal gate

| metric | value | band | verdict |
|---|---|---|---|
| H−L mean %/week | 3.945 | 3.0 – 4.7 | **PASS** |
| Annualised Sharpe | 1.620 | 1.5 – 2.4 | **PASS** |
| Quintiles monotone Q1→Q5 | yes | strictly increasing | **PASS** |

The remaining three bands (CMOM beta, alpha vs LTW, turnover) require the factor
reconstruction and turnover accounting, which are M4.

### Reading the residual gap

The mean matches to **0.04 pp** while the Sharpe is 0.38 low, and the whole
difference sits in the volatility: 17.6% vs 14.4% weekly. That is the expected
consequence of the M1 finding that our universe runs ~16% larger than the authors'
from 2018 onward (a CMC data-vintage effect, diagnosed and deliberately not tuned
away). Extra small, volatile coins raise the spread's variance without changing its
mean much. A Spearman of 0.82 with 84% weekly sign agreement says we are tracking
the same underlying signal week by week, not merely landing on a similar average.

## Three bugs this milestone surfaced, in order of how badly they misled

**1. Alignment — the one that mattered.** The first validation returned Pearson
**−0.037**, sign agreement 51.9%, and non-monotone quintiles. The engine labels
`target_week` as the week whose return CTREND forecasts; the validator joined at
that week and then took `lead(weekly_return)`, scoring every forecast **one week
late**. The failure was in the *validator*, not the signal. Fixing it moved Pearson
−0.037 → 0.591 and turned the quintiles monotone.

This is exactly the off-by-one that `week_map.parquet` was written to prevent — and
it was still made, one module over. Every summary statistic stayed superficially
plausible while the correlation was destroyed, which is why the correlation is the
right diagnostic and the bands alone are not.

**2. Duplicate coin-days.** The snapshot harvest crashed once and the resume left 4
dates in 2020 written twice (11,445 rows, 0.2%). A doubled day makes `n_ret` 8
instead of 7, fails `min_obs='all'`, and voids the **entire coin-week** — collapsing
four cross-sections from ~900 coins to ~18. Because a skipped week leaves the
52-week smoothing window incomplete, each collapse then suppressed the next 52
emissions: **58 CTREND weeks lost from 4 duplicated dates**. De-duplicated at ingest;
383 weeks emitted, up from 325.

**3. Zero prices (found by the M2 gate).** CMC reports `0.0` for sub-denormal
meme-token prices; `close = 0` makes `sma_Xd = SMA/close` infinite, and because ranks
are relative one infinity corrupts a whole week's cross-section. Fixed at ingest.

## Performance note

The walk-forward first ran at ~505 s/week — an 8–15 hour job. Profiling (rather than
guessing) showed `Dataset.asof` at 18 ms/week and `pooled()` at ~0; the cost was
entirely in fitting 200 lambdas **cold**. On this near-collinear design (28 forecast
columns, condition number ~470) cold coordinate descent does not converge inside
`max_iter`: ~7.1 s per fit at small lambda versus **0.67 s for the entire 200-point
path** with warm starts.

Switching to `enet_path` is not merely an optimisation — MATLAB `lasso` computes the
path with warm starts, so the path solver is the **more faithful** port and the
better-converged one. Runtime fell from an estimated 8–15 hours to **under a minute**.

Two of my own benchmarks were wrong before I got this right: the first used
uncorrelated synthetic data (converges instantly, hiding the problem), the second
extrapolated from the five *largest* lambdas (all-zero solutions, 3 ms each) rather
than the five smallest (7 s each).

## Coverage context

Complete-case (all 28 indicators present) is **87.4%** of coin-weeks; high/low
coverage is alive 99.4% / delisted 76.9%. This run used the full panel. The
`--complete-case` restriction remains available for the paper-faithful track, and the
difference between the two is the residual survivorship measurement.
