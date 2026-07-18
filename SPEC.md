# SPEC.md — CTREND ground-truth specification

Originally a verbatim copy of §§4–8 of the master prompt. This file is authoritative.
Ambiguity resolutions are logged in DECISIONS.md.

> **RECONCILED AGAINST THE AUTHORS' CODE — 2026-07-18.** The Dataverse package
> (doi:10.7910/DVN/NTIVT8) ships the authors' MATLAB implementation, i.e. the
> authoritative record of what actually produced the published numbers. Reading it
> against this spec found 12 material divergences from our reading of the paper.
> Corrections are marked **[GT-n]** with `file:line` evidence and carry a config flag
> plus a DECISIONS.md row (invariant I2). Superseded text is struck as ~~[WAS]~~.
>
> These are corrections of our *reading*, identified from primary source **before any
> result was computed**. They are not parameter search and do not engage I3. The §7
> acceptance bands remain immutable and unedited.
>
> Track A ships **no panel data** — see `reports/m1_data_inventory.md`. The panel is
> reconstructed from CMC daily snapshots; the shipped `Results/CTREND/CTREND.xlsx`
> (371 weeks, mean 3.866%/wk, Sharpe 1.944) serves as a week-by-week validation target.

---

## 4. GROUND-TRUTH SPECIFICATION

### 4.1 Data

**Track A — validation backbone.** The authors' replication package: Harvard Dataverse, DOI 10.7910/DVN/NTIVT8 (https://doi.org/10.7910/DVN/NTIVT8). M1 begins with an inventory (files, formats, schema, code language, presence of LTW factor series) and adapts the ingest layer to what actually exists — never assume the schema.

**Track B — extension to the present.** Market cap + volume from CoinGecko or an equivalent provider; executable OHLCV from exchanges via ccxt (Binance primary; Bybit/OKX fallback). Do not architect around CoinMarketCap deep history (enterprise-gated). If the network blocks a source: CP-2.

**Universe and filters (paper).** A valid coin-week requires close price, dollar volume, and market cap; drop observations with market cap above Bitcoin's; market cap >= USD 1M; weekly frequency built from daily data. Maintain a point-in-time universe table **including delisted and dead coins**, with a delisting registry (coin, last-trade date).

**[GT-1] Weekly calendar — there is no rebalancing weekday.** ~~[WAS] weeks end Sunday close (A3).~~ `b02CalculateIndicators.m:16` sets `lResampleLiuEtAl = true`, so the baseline is `Utils/fResampleLiuEtAl.m:53-89`, which ignores weekdays entirely and slices each **calendar year** into fixed 7-day blocks counted from that year's first row: week 1 of year Y = Jan 1–7; every year has exactly 52 weeks (`fix(365/7)`); **week 52 absorbs the remainder and is 8 days long (9 in a leap year)**; the phase resets every January 1, so boundaries drift by 1–2 days per year. Week IDs are `YYYYWW` integers. The Sunday-to-Sunday path (`fResampleDay2Week.m`) is the `false` branch and is never taken — retain it only as the M5 sensitivity axis. Flag `rebalance_weekday: liu_year_blocks | sunday`.

Weekly aggregation methods (`b02:240-328`): all 28 indicators, close and market cap use **`last`** with `min_obs = 1`; returns use **`prod`** of (1+r) − 1 with `min_obs = 'all'` — **any missing day in a week makes the weekly return NaN**; volume uses **`sum`**.

**[GT-2] Return truncation is daily and per-day cross-sectional.** ~~[WAS] weekly, full-sample percentiles, "itself mild look-ahead" (A5).~~ `b02:66-74` calls `fTruncate(mReturns, 0.005, 1, 2)` while `mReturns` is still **daily** (resampling happens later at `b02:285`). `iDim = 2` takes quantiles **across each day's cross-section**; `iMethod = 1` is both tails. `fTruncate.m:27,30` sets outliers to **NaN — it drops, it does not clip**. There is therefore **no full-sample look-ahead in the authors' truncation**, and A5's premise was mistaken. Flag `truncation_mode: daily_cross_sectional`.

Cascade (`b02:76-81`): truncated coin-days are wiped from the price matrix and `fEnsureAllObs` propagates the deletion to market cap, volume, low, high and open. Because weekly returns require `'all'` days, **one truncated day removes the whole coin-week** and perturbs the 20-day Bollinger and 21-day Chaikin windows. Note MATLAB's `NaN ~= NaN → true` means `lChanged` also fires on already-NaN cells, so **every coin loses its first observation**; this is reproducible behaviour, not a bug to fix, when targeting bit-comparability. Flag `first_obs_quirk: faithful | corrected`.

**[GT-3] No risk-free subtraction; stablecoins are excluded.** ~~[WAS] excess returns = weekly return minus the 1-week risk-free rate.~~ `vRiskFree` is constructed at `b01ReadData.m:114-134`, saved at `:175`, and **never read again** anywhere in the package; `fSharpeRatio` is always called with `vRf = 0`. All sorts, regressions, Sharpe ratios and alphas use **raw** returns. Set `risk_free: 0.0`. Separately, `b05CreateCTREND.m:62-74` applies a **stablecoin exclusion** (`lExclStable = true`) that this spec never mentioned — flag `exclude_stablecoins: true`.

Filter application order matters: the **mcap > Bitcoin's** screen is applied **daily at the raw-data stage**, keyed on hard-coded CMC asset id 1, and simultaneously drops `mME <= 0` (`b01ReadData.m:59-62`) — it is framed as data-error removal, not an economic screen. The **mcap >= USD 1M** floor is applied **weekly**, much later, together with a price floor and the stablecoin exclusion (`b05:62-74`).

### 4.2 The 28 technical indicators (daily inputs → weekly cross-sectional rank map to [-0.5, +0.5])

**Momentum oscillators (5):** `rsi` (14d); `stochK` (14d); `stochD` (3d SMA of stochK); `stochRSI` (14d, computed on the rsi series); `cci` (20d).

**Moving averages (9):** `sma_3d`, `sma_5d`, `sma_10d`, `sma_20d`, `sma_50d`, `sma_100d`, `sma_200d` — each a simple moving average of close divided by current close; `macd` — see [GT-4]; `macd_diff_signal` — macd minus its 9d EMA.

**Volume (10):** `volsma_3d`, `volsma_5d`, `volsma_10d`, `volsma_20d`, `volsma_50d`, `volsma_100d`, `volsma_200d` — SMA of dollar volume divided by current dollar volume (denominator zeros → NaN, `b02:210-213`); `volmacd` — the PVO analogue of macd computed on dollar volume ([GT-4] applies); `volmacd_diff_signal` — volmacd minus its 9d EMA; `chaikin` — Chaikin Money Flow, see [GT-5].

**Volatility (4):** `boll_mid` — 20d SMA of close, divided by close; `boll_low` and `boll_high` — mid minus/plus two 20d standard deviations of close, each divided by close; `boll_width` — (high − low) / **mid** (not divided by close; `b02:228`).

The 28-name list above **exactly matches** `b05CreateCTREND.m:78-82` — nothing missing, nothing extra. (`lUseVolume = false` yields a 17-indicator design-choice variant; not baseline.)

**[GT-4] macd / volmacd divide by the SLOW EMA.** ~~[WAS] percentage of the *fast* EMA, per paper text (A1).~~ `b02:199` calls `fPercentagePriceOscillator` — i.e. the **PPO**, not MACD — and `technical_indicators.m:470-477` computes `(mFastMA − mSlowMA) ./ mSlowMA`. Identically for `volmacd` via `fPercentageVolumeOscillator` (`:510`). Windows fast=12, slow=26, signal=9. The unscaled `fMACD` (`:619-647`) exists but is **never called** — do not implement it. Flag `macd_denominator: slow | fast`.

**[GT-5] Chaikin is 21 days with min 10 observations.** ~~[WAS] 20 days (A2).~~ `b02:221` calls `fChaikinMoneyFlow(21, 10)`. Two guards must be copied: zero-range days (`high − low <= 0`) become NaN rather than 0, and zero-volume windows yield NaN (`technical_indicators.m:275-290`). `lNotAvail` masks close/low/high/volume **jointly** before summing. Flags `chaikin_window: 21`, `chaikin_min_obs: 10`.

**[GT-6] The stochastics are bounded [0, 1], not [0, 100].** `stochK` = `(close − LL(low,14)) / (HH(high,14) − LL(low,14))` (`technical_indicators.m:609-613`, min 14 obs); `stochD` = 3d SMA of stochK; `stochRSI` is the same transform on the RSI series with **min 5 obs** (`b02:178`). Only `rsi` (MATLAB `rsindex`, Wilder smoothing) is in [0,100]. Harmless for results — everything is rank-transformed — but the property test below must be corrected. `cci` uses window 20 with **min_obs 10** (`b02:184`), constant 0.015, typical price (C+L+H)/3.

**[GT-7] SMAs have NO warm-up NaN.** `fSimpleMovingAverage` (`technical_indicators.m:100-107`) uses an **expanding** window with `'omitnan'`: `max(1, t−w+1):t`. So `sma_200d` is non-NaN from a coin's first day (where it equals exactly 1.0), and the same holds for every `volsma_*`. The PPO/PVO functions apply no warm-up masking either, so `macd`, `volmacd` and their `_diff_signal` are also never NaN-masked. The binding warm-up is set instead by `boll_*` (20 **consecutive** clean closes — `std`/`mean` without `'omitnan'`, `:667-668`), `chaikin` (21/10), `cci` (20/10), `stochK`/`stochD` (14/14) and `stochRSI` (14/5). Since `b05:115` requires **complete cases across all 28**, this is what actually gates universe entry — naively NaN-masking `sma_200d` for 200 days would discard roughly six months of every coin's life and materially shrink the cross-section. Flag `sma_warmup: expanding | strict`.

EMA convention (`technical_indicators.m:110-164`): smoothing `2/(1+window)`, loop starts at t=2, `mEMA(1,:)` always NaN, a missing previous EMA backfilled with the SMA at t−1. **This is not `pandas.ewm(adjust=False)`** — port the explicit loop.

**Required property tests (corrected):** `rsi` bounded in [0, 100] and `stochK`, `stochD`, `stochRSI` bounded in **[0, 1]** per [GT-6]; NaN until each indicator's warm-up horizon **for the Bollinger/Chaikin/CCI/stochastic families only** — SMA, volSMA and MACD families are expanding and warm-up-free per [GT-7]; SMA-over-close ratios invariant under price rescaling; weekly cross-sectional ranks land in [-0.5, +0.5].

### 4.3 Signal construction — CS-C-ENet, strict weekly walk-forward

Reference implementation: `Utils/fWalkforwardCSENET.m`, called at `b05CreateCTREND.m:143-147`
with `dAlpha = 0.5`, `iNumIn = 52`, `lRoll = true`, `lEstAlpha = true`, `dFracVal = 0`,
`iMinNumObsReg = 10`.

1. Each week *t*, for each indicator *j*: univariate cross-sectional WLS regression of week-*t* returns (raw, not excess — [GT-3]) on the rank-mapped signal observed at *t−1*; regression weights = **lagged** market cap normalized to sum to 1 within the week (`b05:124-128`). Solved by normal equations `(X'WX)\(X'Wy)` with a `pinv` fallback when `rcond < 1e-15` (`fEstFamaMacBethPanel.m:113-120`).

2. **[GT-8] Collapse to a SINGLE (ᾱ_j, β̄_j) pair per indicator per iteration** — the equal-weighted mean of the 52 weekly WLS gammas (`fEstFamaMacBethPanel.m:156-157`), applied **uniformly** to all 52 training weeks *and* to the out-of-sample week (`fPredictFamaMacBethPanel.m:67`). ~~[WAS] trailing means of alpha_jt and beta_jt over M = 52 weeks, recomputed for each training week, producing a different (α,β) per training row.~~ There is no per-week trailing mean and no time variation within the window. Flag `smoothing: window_mean | trailing_mean`.

3. Per-indicator forecast: ᾱ_j + β̄_j × signal.

4. Combining step over the training window: pool weeks and fit ElasticNet with `l1_ratio = 0.5`, `Standardize = true` (X standardized before fitting, coefficients returned on the original scale, so signs — and hence the θ>0 rule — are preserved; sklearn requires standardizing manually and rescaling), `Weights` = the same market-cap vector, and a fitted global intercept.

   **[GT-9] The lambda grid is 200 points and DATA-DEPENDENT.** ~~[WAS] a log-spaced grid of 25 points spanning a fixed 1e-4 to 1.~~ `fEstRegPanelRegression.m:50` defaults `iNumLambda = 200` and `fWalkforwardCSENET.m:196-197` does not override it; `:82-94` calls MATLAB `lasso` with `NumLambda`, whose grid runs geometrically from `lambda_max` (smallest λ zeroing all coefficients, `max|X'y| / (n·l1_ratio)`) down to `1e-4 × lambda_max`, **recomputed for every rolling window**. Port as `np.geomspace(lambda_max, 1e-4*lambda_max, 200)`. Flag `lambda_grid: data_dependent | fixed`.

   > Severity note: an earlier assessment rated the fixed grid critical, on the reasoning that it would sit entirely above `lambda_max` and select nothing. **Tested and not supported** — across signal strengths (corr 0.002–0.04) and panel sizes (n = 3,120 and 15,600), `lambda_max` lands at 0.006–0.014, leaving 11–13 of the 25 fixed points usable in every regime. The real finding is narrower: the two grids selected **different indicator sets in 5 of 10 tested cases**. Adopt the data-dependent grid for fidelity and scale-invariance, not for survival.

   **[GT-10] AICc uses k = nonzero coefficients, with NO +1.** `fEstRegPanelRegression.m:108` computes `n·log(MSE) + 2·DF·n/(n − DF − 1)` where `DF` excludes the intercept. Our penalty `2k + 2k(k+1)/(n−k−1)` factorizes to `2k·n/(n−k−1)` and is **algebraically identical**; only `k` differs. ~~[WAS] k = nonzero + 1.~~ `n` = pooled observations after NaN removal. Selection is a plain `min` over the grid; the all-zero solution is eligible (`iMinNumNonZero = 0`). **Cross-validation is prohibited here (I2)** — and confirmed absent from the authors' code.

   **[GT-11] Only the RETURNS are cross-sectionally demeaned, and equal-weighted.** ~~[WAS] cross-sectionally demean both realized returns and each of the J = 28 forecasts (time fixed effects).~~ `b05:133-137` demeans returns once, with an **equal-weighted** cross-sectional mean, before the panel is built — even though the regressions are value-weighted. The **forecasts are never demeaned**; the combining step fits a single global intercept and `mID` never enters estimation, so **there are no time fixed effects**. The regressors are already mean-zero by construction: `fCrossSectTransChars.m:48-50` applies `tiedrank`, rescales to [0,1], then subtracts 0.5 — confirming the **[−0.5, +0.5]** map. Demeaned returns are used **only** for estimation; the portfolio sorts at `b05:153` use raw returns. Flag `demean: returns_only | returns_and_forecasts`.

5. CTREND = equal-weighted mean of the per-indicator forecasts whose combining coefficient **θ_j > 0 strictly** (not `≠ 0`), the intercept excluded via the `end-iNumIndepVars+1:end` slice (`fWalkforwardCSENET.m:199-207`). A θ-weighted variant is computed but discarded at `b05:143` and is **not** baseline. If nothing is selected, CTREND is NaN. Every quantity at *t* uses data ≤ *t* only.

**Training-window boundaries — verified clean.** For forecast week τ, the pooled training set is weeks **τ−52 … τ−1 inclusive** (fixed-length rolling, `lRoll = true`; `fWalkforwardCSENET.m:100-108`, `fCreateIndices.m:43-44`), with row (i,s) pairing coin *i*'s demeaned return in week *s* against its indicator rank at week **s−1**. Everything is observable by the close of week τ−1. First forecast week = index 53 → `201416 + 52 = 201516`, matching the shipped factor series exactly. Edge case: `vUniqueTimeID` is computed *after* all-NaN rows are dropped, so "52 in-sample periods" means 52 weeks containing at least one valid observation, not 52 calendar weeks.

**In-sample reuse (documented, not a defect).** With `dFracVal = 0`, train and test indices coincide (`fWalkforwardCSENET.m:139-140`), so the elastic net's design matrix consists of **in-sample fitted values** from gammas estimated on those same 52 weeks. Selection is thus evaluated on the data that produced it. No leakage into week τ, but optimistic; the authors knowingly ran a `dFracVal = 0.3` validation variant as a robustness design (`b09RunResearchDesigns.m:276-281`). Flag `val_fraction: 0.0`.

### 4.4 Portfolio construction and evaluation

Weekly quintile sorts on CTREND; value-weighted portfolios (on **lagged** market cap, consistent with the WLS weights); H−L spread; base holding period 1 week (2–6 weeks as diagnostics). Turnover per Gu–Kelly–Xiu (2020): half the sum of absolute weight changes per leg, averaged across the long and short legs — **confirmed** at `fSingleSortMulti.m:403-410` (per leg ½·Σ|w_t − drifted w_{t−1}|; H−L = sum of legs, halved at `b14:168` to report the average). The paper's 68.45% is this quantity. Cost schemes (long/short bps): 30/40, 40/50, 50/60 — **confirmed** (`b14:47-49` with `vTC(1)` = short, `vTC(2)` = long, `fSingleSortMulti.m:352,368-369`). Annualized Sharpe = weekly mean/SD × sqrt(52); Lo (2002) Sharpe-ratio test `t = SR / sqrt((1 + 0.5·SR²)/n)` on the **unannualized** SR — **confirmed** (`fSharpeRatio.m:49`).

**[GT-12] t-statistics are plain OLS/iid, NOT Newey–West.** ~~[WAS] Newey–West t-statistics (statsmodels HAC).~~ The authors use `ttest` on portfolio means (`b06:190`, `b14:158,163`, `fSingleSortMulti.m:391`) and `regstats(..., {'tstat'})` — **OLS** standard errors — for alphas and betas (`b06:202,207`). The paper's α^LTW = 2.62 with **t = 4.22 is an OLS t**. HAC appears only inside `fEstFamaMacBethPanel.m:171` (`bandwidth 12`), for a different table, and that path is bypassed here (`lGammaOnly = true`). Using HAC will change the t-stats relative to the paper and could move the §7 alpha gate. Flag `tstat_method: ols | newey_west`; replication default **ols**, HAC reported alongside as a robustness column.

**Breakeven transaction cost uses a DIFFERENT turnover than the reported figure.** `fSingleSortMulti.m:329` divides average return by `mChWts` = `Σ|w_{t−1} − w_t|` — **not halved and not return-drift-adjusted**, and for the hedge portfolio computed on the net long-minus-short weight vector. Do not reuse the GKX number here. The 5%-significance BETC comes from `fBreakevenTC` with `dAlpha = 0.05`.

**Sort mechanics that differ from a naive `qcut`** (`fSingleSortMulti.m`, `vQuantiles = 0:0.2:1`): breakpoints via MATLAB `quantile(..., 'Method','exact')`, which uses the (i−0.5)/n plotting-position convention with linear interpolation and is **not** `numpy.percentile`'s default — port precisely or breakpoints drift. An entire week is voided if fewer than **`iMinNumCS = 25`** coins have a valid sort variable; **`iMinNumAssets = 5`** per portfolio; `lEnsureAllObs = true` forces joint availability of return, market cap and sort variable *before* breakpoints are computed; the lowest bucket is closed on both sides (`>=`) and the rest left-open (`>`); `iHedgeSign = 1` → **H − L**, long the top quintile.

Alphas versus the CCAPM (CMKT) and the LTW three-factor model. Reconstruct the factors from the project's own panel per Liu–Tsyvinski–Wu (2022): CMKT = value-weighted market excess return; CSMB = bottom-minus-top size terciles (value-weighted); CMOM = top-minus-bottom terciles of 3-week momentum (value-weighted). The authors' in-package reconstruction (`b06:146-159`) **matches this**: CSMB from a 30/70 size sort × (−1); CMOM from a dependent 2×(30/70) sort on 3-week momentum, averaged across size halves. Their baseline (`b06:26`, `lUseLTW = true`) uses Liu's published series in preference to the reconstruction.

The LTW three-factor series is **not** shipped in the package but is publicly downloadable (verified: 479 weekly obs, `yyww` 201404→202314, columns `cmkt|csize|cmom`, 373 obs inside the replication window). Require correlation >= 0.95 with the reconstruction or document the divergence in DECISIONS.md. Note their header: "data are from coingecko since mid-2020."

---

## 5. VERIFIED REFERENCE SEED + GOLDEN TEST

The script below is a verified miniature of §4.3 on synthetic data (5 informative signals planted among 28 with mixed signs). It has been executed and passes: the AICc-selected elastic net recovers exactly the planted set {0, 3, 7, 12, 20}, including the negative-loading signal (whose univariate forecast correctly flips sign). Install it as the basis of `tests/golden/test_cenet_golden.py` (wrap in a pytest function). **Any refactor of `src/ctrend/signal/` must keep this test green, assertions unchanged.**

```python
"""Golden test: CS-C-ENet miniature. Expected selection: exactly {0, 3, 7, 12, 20}."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
from sklearn.linear_model import ElasticNet
from scipy.stats import spearmanr

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
```

---

## 6. MILESTONES & DEFINITION OF DONE

- **M0 — Scaffold.** Tree, Makefile, dependencies, CLAUDE.md/SPEC.md/DECISIONS.md, smoke test, golden test installed and passing, plus `tests/test_no_lookahead.py`: build signals through week *t* on a fixture, replace all data after *t* with random noise, and assert CTREND at *t* is bit-identical. *DoD:* `make test` green.
- **M1 — Data layer.** Track A download + inventory report; ingest to parquet/DuckDB; point-in-time universe with delisting registry; Track B connectors stubbed behind the same `Dataset` interface. *DoD:* yearly coin counts and mean/median market cap and volume within ±2% of the paper's Table 1; dead coins demonstrably present. **CP-1: present the inventory and stop.**
- **M2 — Indicator engine.** All 28 signals; property tests; spot-check three indicators against an independent implementation (the `ta` package) within tolerance. *DoD:* property tests green; 28 columns for every eligible coin-week.
- **M3 — Signal engine.** Production §4.3 behind `Dataset.asof`; CTREND produced for every week from week 53 onward. *DoD:* golden and look-ahead tests green.
- **M4 — Portfolio & evaluation.** Sorts, turnover, costs, statistics, factor reconstruction. *DoD (pipeline canary):* the 3-week-momentum quintile H−L on Track A lands in 2.0–4.0%/week (paper: 3.06) *before* CTREND is judged — this validates the pipeline independently of the novel signal.
- **M5 — Validation.** Run `configs/replication.yaml` on Track A, May 2015 → May 2022; produce `validation_report.md` versus §7; include a rebalancing-weekday sensitivity table. **CP-3: present the report and stop.**
- **M6 — OOS extension + reality layer.** Extend to the present on Track B. Four configurations: paper-faithful; +1-day implementation lag; long-only within the top-half liquidity screen; long-only with a BTC/ETH perpetual beta hedge including funding costs. The feasibility mask (a coin is shortable in week *t* only if a borrow/perp venue existed then) is ON by default in `live.yaml`. *DoD:* decay report — pre/post-May-2022 spreads, rolling 52-week Sharpe, long/short leg decomposition.
- **M7 — only on explicit user request.** Weekly order-sheet harness (CSV output, position and turnover guardrails, logs). I7 stands: no execution.

---

## 7. VALIDATION ACCEPTANCE BANDS (immutable)

| Metric (H−L unless noted) | Paper | Accept iff |
|---|---|---|
| Quintile mean returns | monotone | strictly increasing Q1 → Q5 |
| H−L mean, %/week | 3.87 | 3.0 – 4.7 |
| Annualized Sharpe | 1.94 | 1.5 – 2.4 |
| CMOM beta | 0.79 | 0.6 – 1.0 |
| Alpha vs LTW | 2.62%, t = 4.22 | > 0 with t > 3 |
| Weekly turnover | 68.45% | 55 – 80% |

Interpretation: all pass → proceed to M6. Any fail → STOP; produce a diagnosis (leg-level alphas L vs H, weekday sensitivity, filter counts versus Table 1, indicator distribution sanity checks) and wait for the user. Widening a band, editing a golden test, or re-running with new seeds to force a pass violates I3.

---

## 8. AMBIGUITY LEDGER & FAILURE PROTOCOL

Known ambiguities (the paper is silent or self-conflicting). Implement the default, expose the flag, log the choice in DECISIONS.md:

**A1–A5 are now RESOLVED from the authors' source code — they are no longer ambiguities.**
The original guesses are retained for the record; the resolved column governs.

| ID | Ambiguity | ~~Original guess~~ → **RESOLVED from code** | Config flag |
|---|---|---|---|
| A1 | macd/volmacd denominator | ~~fast EMA (paper text)~~ → **slow EMA** — `b02:199` calls the PPO function; `technical_indicators.m:474,510`. See [GT-4] | `macd_denominator: slow` |
| A2 | Chaikin Money Flow window | ~~20 days~~ → **21 days, min 10 obs** — `b02:221`. See [GT-5] | `chaikin_window: 21`, `chaikin_min_obs: 10` |
| A3 | Rebalancing weekday | ~~Sunday close, hold Mon–Sun~~ → **no weekday exists**; Liu-style fixed 7-day blocks from Jan 1, 52 wk/yr, wk 52 is 8–9 days. See [GT-1] | `rebalance_weekday: liu_year_blocks` |
| A4 | Delisting return convention | **confirmed** — `b01ReadData.m:52` computes returns from close only with no delisting adjustment; the position simply closes at the last observed price | `delisting_policy: last_price` |
| A5 | Truncation timing | ~~full-sample percentiles, mild look-ahead~~ → **daily, per-day cross-sectional, drops to NaN**. The premise was mistaken: the authors' truncation contains **no look-ahead**. See [GT-2] | `truncation_mode: daily_cross_sectional` |

### A6 (new) — a genuine look-ahead bug in the authors' own resampler

`fResampleLiuEtAl.m:109-121`, the `'last'` branch. When a coin has ≥1 observation in a
week but the week's **final day is missing**, the fallback searches `mDataTemp` — the
**calendar-year** slice — instead of `mDataDailyTemp`, the week slice, substituting the
last non-missing value in the entire year. For any week before December that is a
**future** value. The correct week-local logic exists in `fResampleDay2Week.m:102`.

Blast radius: everything resampled with `'last'` — **all 28 indicators**, close and
market cap. Returns (`'prod'`) and volume (`'sum'`) are unaffected. Worst for illiquid,
gappy coins and for coins that die mid-year, where every pre-death week can inherit the
death-week value.

**This collides directly with invariant I1: a faithful port FAILS `tests/test_no_lookahead.py`
by construction.** Resolution: `liu_resample_lastfix: corrected | faithful`, defaulting to
**corrected** so I1 holds, with `faithful` available to quantify the gap against the shipped
`CTREND.xlsx`. If the reconstruction lands below the §7 band, this is a prime suspect for
part of the difference.

Anything else ambiguous: choose the most conservative reading, add a flag, log it. Data source unavailable → smallest viable fallback and CP-2. Never fabricate data; never delete a failing test; pin all dependency versions in a lockfile.
