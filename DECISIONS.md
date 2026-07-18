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
| 2026-07-18 | CLAUDE.md I5 says "pandas/polars"; polars is neither installed nor a pyproject dependency | pandas + numpy + pyarrow + duckdb. I5's "polars" is aspirational, not a requirement. | n/a |
| 2026-07-18 | Bit-identity is an environment property as much as a code property; DECISIONS row 13 claimed a `.python-version` and `uv.lock` that did not exist on disk | both produced (`uv lock`, Python 3.12); `tests/conftest.py` additionally caps BLAS threads to 1 before numpy is imported, since thread count changes float reduction order | n/a |
