# DECISIONS.md — ambiguity ledger

Every deviation from SPEC.md requires a row here plus a config flag (invariant I2).
Ambiguity IDs A1–A5 are defined in SPEC.md §8.

| date | ambiguity | choice | config flag |
|---|---|---|---|
| 2026-07-18 | A1 — macd/volmacd denominator: paper text says percentage of the *fast* EMA; conventional PPO/PVO divide by the *slow* | fast EMA (paper text), per SPEC default | `macd_denominator: fast` |
| 2026-07-18 | A2 — Chaikin Money Flow window unstated | 20 days, per SPEC default | `chaikin_window: 20` |
| 2026-07-18 | A3 — Rebalancing weekday unstated | weeks end Sunday close; positions held Monday–Sunday | `rebalance_weekday: sunday` |
| 2026-07-18 | A4 — Delisting return convention unstated | close position at last observed price; live mode additionally excludes non-shortable names via feasibility mask | `delisting_policy: last_price` |
| 2026-07-18 | A5 — Truncation timing (paper uses full-sample percentiles — itself mild look-ahead) | replication: full-sample; live: expanding window | `truncation_mode: full_sample` / `expanding` |
| 2026-07-18 | Python interpreter version unpinned by SPEC (requires 3.11+) | Pinned 3.12 via uv. System default is 3.13.5 (miniconda); 3.12 chosen for broadest wheel coverage across statsmodels/pyarrow/duckdb. Recorded in `.python-version` + `uv.lock`. | n/a (`.python-version`) |
| 2026-07-18 | Repository location: `/Users/vakof` (home dir) is itself a git repo; CTREND is a subdirectory | `git init` created CTREND as an independent nested repo, so parquet data and `.env` cannot leak into the home-directory repo. Satisfies SPEC §2 step 1 and invariant I6. | n/a |
| 2026-07-18 | §4.1 says "truncated cross-sectionally" but the A5 default is "full-sample percentiles". A strictly per-week cross-sectional percentile would contain NO look-ahead, contradicting A5's own premise that the paper's choice *is* mild look-ahead. | Only self-consistent reading: thresholds pooled over all coin-weeks | `returns.truncation_scope: pooled` |
| 2026-07-18 | §4.3 step 4 never defines "the training window" | expanding: combining targets [53, t] | `signal.training_window: expanding \| rolling:<n>` |
| 2026-07-18 | SPEC §6 M3 says "week 53 onward", but the pool of combining targets is empty at signal week 52, so no ENet can be fit there | first CTREND target week = 54; `min_pool_weeks = 1` | `signal.min_pool_weeks: 1` |
| 2026-07-18 | Forecast alignment. The §5 golden indexes every quantity by the week whose return it explains (its "forecast at t" uses `Z[t-1]`), which is right for the training design but would mislabel an emitted value as a forecast for t+1. | Training design reproduces the golden exactly; the EMITTED CTREND follows §4.3 step 3 literally — forecast for t+1 uses smoothed pairs [t+1−M, t] and the signal at t, all known at t. Verified in `tests/test_golden_parity.py`: the engine's emission at signal week 88 coincides bit-for-bit in construction with the golden's holdout at t=89. | `signal.forecast_alignment: t_plus_1` |
| 2026-07-18 | WLS market-cap timing (t vs t−1); the golden's time-invariant mcap vector cannot arbitrate | t−1, the signal date (conservative under I1) | `signal.wls_weight_date: signal` |
| 2026-07-18 | WLS weight normalization — beta is scale-invariant under a rescale of mcap only because zm/rm are genuine weighted means; alpha depends on it | normalize to sum 1 (golden) | `signal.wls_weights_normalize: true` |
| 2026-07-18 | Step 4 demeans realized returns equal-weighted while step 1 uses value weights — an asymmetry the SPEC does not comment on | preserve the asymmetry (literal reading of "cross-sectionally demean"), logged | `signal.demean_returns: equal_weight` |
| 2026-07-18 | Degenerate cross-sectional variance guard exists only in the §5 golden, not in §4.3 | 1e-12 floor, as in the golden | `signal.var_floor: 1.0e-12` |
| 2026-07-18 | Minimum admissible cross-section per weekly WLS is unspecified | 20 coins; smaller weeks are skipped and logged | `signal.min_cross_section: 20` |
| 2026-07-18 | Coin present at t but absent at t−1 (interacts with A4 and with dead coins) | inner join: the coin must be eligible at both t−1 and t, else it is dropped from that week's regression. Compaction, not zero-weight padding — padding perturbs the `np.sum` reductions at ~1e-15 and would silently break bit-identity. | `signal.nan_policy: inner_join` |
| 2026-07-18 | Empty selection (no theta_j > 0): the golden's `.mean(1)` over an empty axis yields NaN, unguarded | NaN, explicit; the week is dropped downstream and logged | `signal.empty_selection: nan` |
| 2026-07-18 | A4 `delisting_policy: last_price` was logged above but absent from both config files — an I2 violation on disk | added to `configs/replication.yaml` and `configs/live.yaml` | `universe.delisting_policy: last_price` |
| 2026-07-18 | DEVELOPMENT.md I5 says "pandas/polars"; polars is neither installed nor a pyproject dependency | pandas + numpy + pyarrow + duckdb. I5's "polars" is aspirational, not a requirement. | n/a |
| 2026-07-18 | Bit-identity is an environment property as much as a code property; DECISIONS row 13 claimed a `.python-version` and `uv.lock` that did not exist on disk | both produced (`uv lock`, Python 3.12); `tests/conftest.py` additionally caps BLAS threads to 1 before numpy is imported, since thread count changes float reduction order | n/a |

---

# Part 2 — Ground-truth reconciliation against the authors' MATLAB code

Added 2026-07-18, **after** the rows above were written. The Dataverse package
(doi:10.7910/DVN/NTIVT8) ships the authors' MATLAB implementation — the authoritative
record of what produced the published numbers. Reading it against SPEC.md found 12
material divergences plus one bug in the authors' own code.

**User decision (2026-07-18): rewrite SPEC.md to match the authors' code.** Every
change is flagged and logged below. These corrections were identified from primary
source **before any result was computed**; they are not parameter search and do not
engage I3. The §7 acceptance bands are unedited and remain the hard gate (user
decision, same date).

Rows above are retained for audit. **Superseded by this section:** the A1 row
(fast→slow), A2 (20→21), A3 (sunday→liu_year_blocks), A5 (full_sample→daily
cross-sectional), `returns.truncation_scope: pooled` (the pooling question is moot —
truncation is per-day), and `signal.training_window: expanding` (the authors use a
fixed 52-week rolling window). The remaining workflow rows stand; notably
`signal.demean_returns: equal_weight` is **independently confirmed correct** by GT-11.

| ID | Divergence | Choice | Config flag |
|---|---|---|---|
| GT-1 | Weekly calendar: SPEC assumed Sunday-ending weeks; code uses Liu-style fixed 7-day blocks from Jan 1, 52 wk/yr, wk 52 = 8–9 days, phase resets annually (`fResampleLiuEtAl.m:53-89`) | Adopt Liu year-blocks; keep Sunday as the M5 sensitivity axis | `rebalance_weekday: liu_year_blocks \| sunday` |
| GT-2 | Truncation: SPEC said weekly + full-sample percentiles; code truncates **daily, per-day cross-sectional**, dropping to NaN (`b02:66-74`, `fTruncate.m:27,30`) | Adopt daily cross-sectional. A5's look-ahead premise was mistaken — there is none | `truncation_mode: daily_cross_sectional` |
| GT-2b | Cascade wipes the coin-day from price/mcap/vol/OHLC; MATLAB `NaN ~= NaN` also drops **every coin's first observation** (`b02:76-81`) | Reproduce faithfully for bit-comparability; expose a corrected variant | `first_obs_quirk: faithful \| corrected` |
| GT-3 | Risk-free: SPEC specified excess returns; `vRiskFree` is written and **never read** — all returns raw | `risk_free: 0.0` | `risk_free: 0.0` |
| GT-3b | Stablecoin exclusion is a baseline filter (`b05:62-74`) that SPEC omitted entirely | Add it | `exclude_stablecoins: true` |
| GT-4 | macd/volmacd divide by the **slow** EMA — code calls PPO/PVO (`b02:199`, `ti.m:474,510`). Resolves A1 against SPEC's default | Adopt slow | `macd_denominator: slow \| fast` |
| GT-5 | Chaikin window is **21** with min 10 obs, not 20. Resolves A2 | Adopt 21/10 | `chaikin_window: 21`, `chaikin_min_obs: 10` |
| GT-6 | stochK/stochD/stochRSI are bounded **[0,1]**, not [0,100]; SPEC's property test would fail a faithful port | Correct the property test | n/a (test fix) |
| GT-7 | SMA/volSMA/MACD families use an **expanding** window with no warm-up NaN; `sma_200d` is non-NaN from day 1 (`ti.m:100-107`). Naive masking would discard ~6 months per coin and shrink the cross-section | Adopt expanding | `sma_warmup: expanding \| strict` |
| GT-8 | α/β smoothing: SPEC specified per-week trailing means; code collapses to a **single (ᾱ,β̄) pair** — the mean of 52 weekly gammas — applied uniformly to all training weeks and the OOS week (`fEstFamaMacBethPanel.m:156-157`) | Adopt window mean | `smoothing: window_mean \| trailing_mean` |
| GT-9 | Lambda grid: SPEC specified 25 fixed points on [1e-4, 1]; code uses **200 data-dependent** points from `lambda_max` to `1e-4·lambda_max`, recomputed per window | Adopt data-dependent | `lambda_grid: data_dependent \| fixed` |
| GT-10 | AICc `k` = nonzero coefficients, **no +1**. Penalty otherwise algebraically identical (`2k+2k(k+1)/(n−k−1) ≡ 2k·n/(n−k−1)`) | Drop the +1 | `aicc_k: nonzero` |
| GT-11 | Demeaning: SPEC demeaned returns **and** forecasts with time FE; code demeans **only returns**, equal-weighted, and fits a single global intercept — no time FE (`b05:133-137`) | Adopt returns-only | `demean: returns_only \| returns_and_forecasts` |
| GT-12 | t-statistics are plain **OLS/iid**, not Newey–West; the paper's t = 4.22 is an OLS t (`b06:202,207`) | Replication default OLS; report HAC as a robustness column | `tstat_method: ols \| newey_west` |
| A6 | **Look-ahead bug in the authors' resampler**: a week missing its final day back-fills from the last non-missing value in the whole **calendar year** — a future value (`fResampleLiuEtAl.m:109-121`) | Default **corrected**, so invariant I1 holds. `faithful` retained to quantify the gap against the shipped factor | `liu_resample_lastfix: corrected \| faithful` |

Confirmed correct in SPEC, no change: the 28-indicator list (exact match), market-cap
WLS weights (lagged, normalized), θ_j > 0 strict selection, equal-weighting of
survivors, the [−0.5,+0.5] rank map, GKX turnover, the 30/40–50/60 bps cost schemes,
the Lo (2002) Sharpe test, and the LTW factor reconstruction. No cross-validation
appears anywhere in the authors' code — I2 is consistent with it.

### Severity correction (recorded for honesty)

The initial extraction rated GT-9 critical, reasoning that SPEC's fixed grid sits
entirely above `lambda_max` so **nothing would be selected** and CTREND would be
degenerate. **Tested and not supported**: across signal strengths (corr 0.002–0.04)
and panel sizes (n = 3,120 and 15,600), `lambda_max` lands at 0.006–0.014, leaving
11–13 of the 25 fixed points usable in every regime. The real finding is narrower —
the two grids selected **different indicator sets in 5 of 10 tested cases**. The
data-dependent grid is adopted for fidelity and scale-invariance, not survival.

---

# Part 3 — Data sourcing

| date | decision | rationale |
|---|---|---|
| 2026-07-18 | **Track A ships no panel data** — 68 files of MATLAB + the factor series | `b01ReadData.m` expects six `*_cmc.csv` files never redistributed; `b01GenerateArtificialData.m` produces Gaussian noise the readme calls "only useful for technical check". The M1 DoD (±2% of Table 1) is unachievable from Track A |
| 2026-07-18 | **Panel reconstructed from CMC daily snapshots** (user-authorized, CP-2) | Verified point-in-time and survivorship-free: BitConnect present at rank 26 on 2018-01-07 with $2.33B mcap. Confirmed that no academic replication package anywhere publishes a coin-level crypto panel |
| 2026-07-18 | CMC endpoint is **undocumented**; terms prohibit redistribution | Harvest once to parquet; never call live from the pipeline. `data/` is gitignored. The raw panel **must not ship** in a replication package — see open question below |
| 2026-07-18 | **Validation target added**: shipped `Results/CTREND/CTREND.xlsx` | 371 weeks, verified mean 3.866%/wk and Sharpe 1.944 vs the paper's 3.87/1.94. Enables week-by-week correlation — stronger than the §7 bands alone. Reported alongside, not in place of, the §7 gate |
| 2026-07-18 | LTW three-factor series sourced from yukunliu.com | Verified: 479 weekly obs `yyww` 201404→202314, 373 inside the window. Satisfies the §4.4 ≥0.95 correlation cross-check |
| 2026-07-18 | High/low unavailable from the CMC snapshot endpoint | Affects 4 of 28 indicators (stochK, stochD, cci, chaikin). CMC's per-coin OHLC endpoint is survivorship-biased exactly where the alpha lives (2018-01 smallest quintile ~35% coverage vs ~90% largest). **OPEN — needs a documented handling rule** |

## Part 4 — M1 curation findings (2026-07-19)

| date | finding | resolution |
|---|---|---|
| 2026-07-19 | **GT-8 implemented.** `state.py` now honours `smoothing: window_mean` (one (ᾱ,β̄) per iteration, applied to all training weeks and the OOS week) and `training_window: rolling:52`. Because the pair belongs to the *iteration*, the pooled design is rebuilt per forecast week rather than accumulated | `smoothing`, `training_window` now change behaviour, asserted by `tests/signal/test_state.py` |
| 2026-07-19 | **First CTREND target moved 54 → 53.** Under `window_mean` the in-sample block is the M weeks *ending at* the signal week, so the first emission is target 53 — matching SPEC §6 M3 ("week 53 onward") and the authors' own first forecast (201416 + 52 = 201516). The old 54 was an artifact of the trailing-mean pool | test constants updated; engine docstring corrected |
| 2026-07-19 | **GT-2b is unreachable at weekly granularity.** A coin's first day has a NULL return by construction, so the block containing it already fails `min_obs='all'` and is voided in *both* modes. The MATLAB `NaN ~= NaN` quirk therefore costs nothing in replication fidelity | `faithful`/`corrected` are interchangeable downstream of weekly aggregation; ratchet test retains the fact |
| 2026-07-19 | **Bug found by test: coin-weeks with an undefined return were surviving curation.** `b05CreateCTREND.m:115` `lAvail` requires `~isnan(mReturns)`, so a block voided by `min_obs='all'` is not a valid coin-week | added `WHERE ret_all IS NOT NULL`; removed 11,591 invalid coin-weeks (281,771 → 270,180) |
| 2026-07-19 | **Curated panel validates against the shipped factor's geometry**: 371 weekly blocks spanning 201516 → 202222, exactly the 371 rows of `Results/CTREND/CTREND.xlsx` | independent confirmation of GT-1 and the sample window |
| 2026-07-19 | Some weeks have a cross-section below the authors' `iMinNumCS = 25` (min observed 18, median 821) | those weeks must be voided at the sort stage per `fSingleSortMulti.m:129-130`; M4 work |

**M1 result.** 270,180 coin-weeks, 3,799 coins, **2,358 delisted (62.1%)** — dead coins
demonstrably retained (BitConnect 76 weeks to 201831, Centra 31 weeks, TerraUSD).
The 62.1% attrition is consistent with the survivorship literature (Nomics' own
global ticker showed only 41% of coins active) and is the reason the paper's short
leg cannot be reproduced from any survivor-only source.

**M1 DoD — GATE RUN 2026-07-19, RESULT: FAIL (14/40 cells).** The paper was supplied,
so the ±2% comparison against Table 1 (p. 3122) was performed. Full analysis in
`reports/m1_table1_gate.md`. Per I3 this is a STOP with diagnosis; **nothing was
tuned in response.**

| finding | evidence |
|---|---|
| **2015–2017 is near-exact** — mean market cap within 0.1%–1.6% for three consecutive years, 2017 passes 4 of 5 statistics | strong evidence GT-1, GT-2, the filter order and the aggregation are all correct |
| **2018+ diverges monotonically**: counts high (+5.6%→+25%), mean mcap and mean volume low (−1.7%→−14.7%, −2.0%→−45.8%) | signature of a larger universe of small illiquid coins, i.e. **data vintage** — authors pulled CMC in 2022–23, we harvested the same endpoint in 2026 after backfill. Grows with time-of-sample exactly as observed |
| Full-sample coins 3,769 vs 3,245 (+16.1%) | same cause |
| **OPEN: median volume runs +6%→+21% high in EVERY year**, including years where counts and means match | a *level* effect in the volume variable, not composition. Hypothesis: CMC `volume24h` is rolling-24h at snapshot time vs the authors' daily-bucketed `volume_cmc.csv`. **Must be resolved before M2 volume indicators are trusted** |

**Paper errors identified (recorded, ours are correct):**
* §III.A says the window yields "**423** weekly observations"; the shipped factor has **371** (201516→202222) and our independent Liu-block calendar produces **exactly 371**. 423 is an error.
* §III.A text says 3,244 unique coins; Table 1 says 3,245.
* §III.B says macd is a percentage of the **fast** EMA, but footnote 3 says this makes it "equivalent to the **percentage price oscillator (PPO)**" — PPO divides by the **slow** EMA. The footnote agrees with the code. **GT-4 (`macd_denominator: slow`) is confirmed correct**; the body text is the paper's error.

**Paper confirms:** GT-8 rolling-52 ("a fixed rolling window of 52 weeks", §III.C);
GT-2 daily truncation (fn. 1: the Bitcoin filter "eliminates a total of ten **daily**
observations"); GKX turnover and the 30/40 bps scheme (§VII.B); and every §7 band.

**New gate available for M2:** Table 2 publishes H−L returns *and* t-statistics for
all 28 individual indicators (rsi +3.52, stochK +3.96, cci +3.80, boll_mid −3.50,
sma_20d −3.13, sma_5d −2.90 …). Several are negative, so sign errors cannot hide.
This supersedes SPEC's weaker "spot-check three indicators against `ta`" and is
insensitive to the vintage-driven universe drift above — it is the right M2 gate.

### KNOWN GAP — RESOLVED 2026-07-19: GT-8 is now implemented

*(The gap recorded below was closed; the text is retained for audit.)*

### ~~KNOWN GAP — GT-8 is declared but NOT yet implemented (M3 work)~~

`make test` is green (79 passed), but green is **not** evidence of ground-truth
conformance here. Two GT flags are validated by `ctrend.config` and honoured by no
code path:

| Flag | Config says | `src/` actually does |
|---|---|---|
| `signal.smoothing` | `window_mean` (GT-8) | `state.smoothed()` computes **trailing means** over `[target-M, target-1]`, recomputed per target week — the superseded algorithm |
| `signal.training_window` | `rolling:52` (GT-8) | `state.pooled()` pools **expanding** targets `[53, t]`; the docstring still cites the old resolution |

The suite passes because no test asserts the engine honours either flag —
`test_golden_parity` pins the golden's own `trailing_mean` behaviour, and
`test_production_default_diverges_from_the_golden` is satisfied by the GT-9/GT-10
divergence alone. This is precisely the config-vs-code drift invariant I2 exists to
prevent, so it is recorded here rather than left to be discovered later.

**Consequence: any CTREND produced today runs the superseded §4.3 steps 2–4.**
Implementing GT-8 in `state.py` and adding tests that assert each flag changes
behaviour is the first task of M3, before any number is reported.

## Part 5 — High/low backfill for the four H/L indicators (2026-07-19)

User direction: **follow the paper path** (all 28 indicators with real high/low).

| date | finding | resolution |
|---|---|---|
| 2026-07-19 | **The CMC historical endpoint silently DOWN-SAMPLES long requests.** It fits a ~732-point cap by widening the interval rather than truncating or erroring: a 2012–2023 request for BTC returns 732 rows at **6-day spacing** (725 gaps of exactly 6 days); the same range in one-year slices returns true daily bars. Six-daily data is useless for 14- and 20-day indicator windows, and the silence is the hazard — it yields plausible, wrong indicators | fetch in `CHUNK_DAYS = 360` slices and de-duplicate. Verified: BTC 2015–2017 returns 1,096 rows, all 1-day gaps. **The entire first OHLC layer was discarded and re-harvested** |
| 2026-07-19 | First harvest logged **116 HTTP 429s** whose coins were recorded as "no OHLC available" — a rate-limit artifact masquerading as genuine absence, biasing the coverage statistic downward | deleted all 1,236 empty results and re-probed at 2 workers; **55 coins recovered**. Coverage figures below are post-correction |
| 2026-07-19 | **OHLC coverage census** (all 3,799 panel coins): alive **99.3%** of coin-weeks, delisted **59.3%**, total **82.2%** | applying the paper's complete-case rule literally drops **48,202 coin-weeks, of which 47,182 (97.9%) are delisted** |
| 2026-07-19 | Only `high` and `low` are joined from the per-coin endpoint; its close/volume/market cap are ignored | that endpoint is the survivorship-biased one. Letting it supply core fields would import the bias into the **universe definition** rather than confining it to four indicators. The snapshot panel stays authoritative |
| 2026-07-19 | The 28 indicators are implemented in `ctrend/indicators/technical.py` with 21 property tests asserting the **corrected** GT-4…GT-7 behaviour | a test asserting the MATLAB EMA *differs* from `pandas.ewm(adjust=False)` **failed and was wrong**: on a gapless series the SMA seeding differs only at t=0, so they coincide from t=1. Replaced with a hand-computed recursion check plus an explicit non-divergence test, so the coincidence is not later mistaken for a port bug |

### Gandal CC0 layer + independent cross-validation (2026-07-19)

User direction: **do Gandal first, then resume CMC.** Both Dataverse deposits were
ingested (`doi:10.7910/DVN/JPEF8T` coins, `doi:10.7910/DVN/H98LCZ` tokens; 1.41M rows,
2,952 distinct names, 2013-04-28 → 2019-10-21).

**Identity had to be earned, not assumed.** Neither file carries a CMC id (the token
file's `id` column is entirely NaN) and the two use different naming conventions —
`"NEO (ANS)"` vs a bare `"Mothership"`. Symbols collide across coins, so a name match
alone could inject another asset's prices into four indicators. Every candidate match
is therefore **validated against this panel's own closes** on overlapping dates and
rejected unless the series agree:

| outcome | n | note |
|---|---|---|
| verified | 1,611 | **1,502 of 1,643 (91%) agree to under 0.1%** — same asset, same upstream |
| **rejected** | 30 | price disagreement; worst at 0.97 and 0.58 log-deviation (generic names like "next", "karma" colliding) |
| too thin | 34 | fewer than 20 overlapping days to judge on |

Result: **909,647 daily OHLC rows across 1,601 coins**, contributing 727,740 daily
H/L rows — more than the CMC layer currently holds.

**Independent cross-check (CMC vs Gandal on the same coin-days).** 186,876 overlapping
coin-days across 269 coins: median |log ratio| **0.00001** for both high and low;
99.2% of highs and 98.9% of lows agree within 1%. Two independent scrapes of the same
upstream, years apart, agreeing to five decimal places — this validates the Gandal
name-matching *and* the chunked CMC fetch simultaneously.

**Gandal narrows the survivorship gap**, which was the point: with CMC covering only
the 312 coins re-fetched so far, combined coverage is alive 45.2% / delisted 40.1% —
a 5-point gap, against the 40-point gap (99.3% / 59.3%) that CMC alone produced.

**Rate-limit incident.** CMC returned `HTTP/2 429` from CloudFront (empty body) after
the harvesting bursts. Cause was self-inflicted: `CHUNK_DAYS = 360` multiplied requests
~10× per coin. A **720-day chunk stays inside the 732-point cap** (verified: 721 rows,
1-day gaps) and halves the request count. Harvest resumed at 3 workers / 0.5s once the
cooldown lifted.

**Still open — the uncovered-coin-week rule.** Three options, none yet chosen by the
user; default is (1):
1. **Two-track** — primary 28 indicators on the H/L-covered subset (paper-faithful),
   secondary 24 indicators on the complete universe (survivorship-free). The gap
   between them *measures* the survivorship effect, which is itself a result.
2. **Complete-case only** — literal paper path, documented bias, inflated H−L.
3. **Relax complete-case** — keep every coin-week, let the four H/L forecasts be NaN
   and average surviving forecasts. Preserves the universe, deviates from `b05:115`.

**Still open — median volume.** Runs +6% to +21% high in every year including those
where counts and means match to 0.1%. A level effect in the variable, not composition.
Affects the ten volume indicators; Table 2 comparisons on that group are not
trustworthy until it is resolved.

### Open question for the user

CMC's terms forbid redistributing the panel, which conflicts with the §9 deliverable
("`make all` reproduces Track A end-to-end from a clean checkout"). **CoinCodex** is
free, has history to 2010, retains 29,137 explicitly-flagged defunct coins, and is
licensed **CC BY-NC 4.0** — an affirmative redistribution grant, the only one found in
the field. Its April-2015 breadth is thinner (253 assets with confirmed pre-2015
`trading_since` vs CMC's ~550). Options: ship a rebuild script rather than data, or
add CoinCodex as a redistributable secondary panel.
