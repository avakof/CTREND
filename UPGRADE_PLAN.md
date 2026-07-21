# Upgrade experiment — plan

## Context

The replication passes all seven acceptance bands in-sample (2015–2022) and matches the
authors' own factor series week by week. Out of sample it does not survive in any
implementable form:

| | 2024–26 (133 weeks) |
|---|---|
| frictionless H−L | +0.52%/wk, Sharpe 0.50, max DD −62.1% |
| long-only | +5.4% vs market +11.6%; negative net of costs |
| short-only | −64.5% gross, ~−78% net, 87.8% max DD |
| market-neutral long leg | −11.1% (t = −0.16) |

Diagnosis: the signal has cross-sectional information, but it concentrates in the part
of the cross-section that cannot be traded — only 18.9% of bottom-quintile names had a
live perpetual, turnover is ~70%/wk against a 1.41% breakeven, and skew is −2.74.

This experiment tests six upgrades against that diagnosis and measures their effect on
**2024–2026**.

---

## Protocol (decided with the user, and binding)

**Split.** Parameters are fitted on **202223–202352 (82 weeks)**, frozen to disk, then
evaluated **once** on **202401–202629 (133 weeks)**. The test window is never used for
selection.

**Scope.** Each upgrade individually versus baseline, plus the cumulative stack — about
ten configurations. All are reported, winners and losers.

**Universe.** Upgrade 1 re-ranks and re-estimates inside the sub-universe. Filtering
existing scores post hoc is not the same experiment and is not what is being tested.

### ⚠ The tuning window is not representative of the test window

| split | weeks | mean %/wk | Sharpe | max DD |
|---|---|---|---|---|
| tune 202223–202352 | 82 | **1.85** | **2.77** | −15.0% |
| test 202401–202629 | 133 | **0.52** | **0.50** | −62.1% |

The tuning period is a *far* stronger regime than the test period. Parameters chosen
there may simply not transfer. A null result is a genuine possibility that must not be
explained away afterwards.

---

## Three verified findings that reshape the experiment

These were measured, not assumed. Each changes the design.

### F1 — The shortable universe is one coin wearing a trenchcoat

| week | n coins | BTC weight | effective N | top-5 weight |
|---|---|---|---|---|
| 202223 | 123 | 0.573 | **2.7** | 0.869 |
| 202401 | 220 | 0.599 | **2.5** | 0.865 |
| 202629 | 576 | 0.683 | **2.1** | 0.900 |

Effective N = 1/Herfindahl. **A value-weighted quintile in this universe *is* BTC.**
Upgrade 1 run paper-faithfully would produce a weekly coin-flip on which bucket BTC's
CTREND rank lands in, and the result would be uninterpretable as a cross-sectional test.

**Therefore, pre-registered before any result is seen:** C1's primary construction is
value-weighted with a **10% per-name cap** on leg weight, residual redistributed
pro-rata among uncapped names. Uncapped VW and equal-weighted are reported as the two
robustness axes. Every configuration reports per-week `effective_n` and `top1_weight`
per leg. If `top1_weight` exceeds 0.5 in more than a quarter of weeks, that goes in the
headline, not a footnote.

### F2 — The test window cannot detect an effect on the level of returns

Baseline on 202401–202629: n = 133, mean 0.52%/wk, **sd 7.53%/wk**.

| threshold | minimum detectable effect, 80% power |
|---|---|
| one-sided α = 0.05 | **1.62%/wk** |
| Bonferroni α = 0.005 | **2.23%/wk** |

An upgrade would have to roughly **quadruple** the baseline to be declarable on levels.
That will not happen, and an experiment designed around it would produce a
foregone-conclusion null.

**Therefore:** the primary statistic is the **paired weekly difference**
`d_k,t = r_k,t − r_0,t` on the 133 common weeks, testing `H0: E[d_k] ≤ 0`. Overlays
share the same underlying signal, so sd(diff) is far smaller than sd(level). sd(diff)
is computed for every configuration on the tuning window and **the resulting MDE is
written into `configs/frozen_params.yaml` before the evaluation runs**. Stating what
could have been detected, in advance, is what makes a null interpretable rather than
disappointing.

Corollary to state up front: this experiment is well powered on **Sharpe, drawdown,
turnover and capacity**, and poorly powered on mean return.

### F3 — The feasibility mask is survivorship-biased, in the direction that flatters U1

`feasibility_mask.py:50` calls Binance `exchangeInfo` **live**, which returns only
contracts existing today. Every perpetual ever fully delisted is silently absent, so a
coin with a live perp from 2022–24 that was later removed is recorded as
never-shortable. Confirmed: the module reads `x["status"]` at line 62 and then discards
it — the output carries `coin_id, symbol, onboard_week` and **no offboard column**.

This biases the constructed universe toward names that survived as perpetuals, i.e.
toward winners. Required guardrails:

1. **Snapshot, never fetch, during the experiment** — `--snapshot data/raw/binance_exchange_info_YYYYMMDD.json`; a mask that changes between runs makes the experiment irreproducible.
2. **Capture offboarding** — keep `status`, add `offboard_week`, make the predicate the interval `onboard_week <= t <= offboard_week`.
3. **Declare it** — this is a second sanctioned leakage channel under I1, so it needs a `Dataset.leakage_channels()` entry and a DECISIONS.md row alongside `A5_truncation`, and the report must state it as a survivor-biased *upper* bound on the shortable universe while remaining a *lower* bound on shortability overall.

---

## Key design decision

The exploration changed the architecture. The obvious injection point for a restricted
universe is the eligibility SQL in `data/store.py:93-102`, which would propagate
automatically to the WLS gammas, the pooled design and the emission.

**But that does not re-rank.** The `z0..z27` values are cross-sectional ranks computed
over the full universe in `indicators/pipeline.py` (`rank_map`, line ~46) and then baked
into the curated panel. Restricting at the store would leave full-universe ranks in
place — the coin ranked 0.5 among 1,800 coins is not the coin ranked 0.5 among 400.

Since the user chose genuine re-estimation, the filter must go **upstream of the rank
map**. That has a useful consequence: if `to_curated` only writes shortable coin-weeks,
the store sees only them, so **no change to `store.py`, `universe.py::filter_counts`, or
the config schema is needed at all**, and none of the tests that pin the eligibility SQL
(`tests/data/test_dataset_asof.py:98`, `tests/data/test_universe.py:55`) are touched.

Filtering is expressed as **CLI arguments and separate output paths**, never by editing
`configs/replication.yaml` or `live.yaml` — `tests/test_smoke.py:83-107` pins eleven
values in those two files by name.

---

## Phase 0 — safety net (do first)

`portfolio/sorts.py` holds the most intricate arithmetic in the repo (GKX turnover,
three distinct weight-change definitions) and **has no test file at all**. Phases 3 and
5 modify it.

- **New** `tests/portfolio/test_sorts.py` — characterization tests pinning current
  behaviour *before* any change: `_leg_turnover` drift adjustment, opening-book = full
  turnover, cost using the undrifted change, quintile boundary rules
  (`sorts.py:89,93`), and that each leg's weights sum to 1.
- Snapshot baseline: copy `reports/m6_variants.csv` → `reports/baseline_m6_variants.csv`.

Runtime: ~10 min to write, seconds to run.

---

## Phase 1 — U1: shortable-universe re-estimation *(highest value, run first)*

Everything downstream operates on U1's output, so it must land before the others.

1. **`ingest/to_curated.py:60`** — add `--universe-mask PATH` and `--as-of-column`.
   Translate `feasibility_mask.parquet` (`coin_id, symbol, onboard_week` in `YYYYWW`)
   through the existing `wmap` (already registered at line 73) and inner-join the panel
   on `onboard_week <= week_id`. Emit to `--out data/curated_u1`.
2. **`indicators/pipeline.py`** — add `--universe-mask` and apply it **before**
   `rank_map` so ranks are computed within the traded universe. Output
   `signals_weekly_u1.parquet`.
3. Run `run_m3 --curated data/curated_u1 --out data/curated/ctrend_weekly_u1.parquet`.

The as-of comparison mirrors what `m6_variants.py:56-58` already does
(`onboard_week <= week`), moved upstream — no look-ahead, and `run_m3`'s existing
calendar/week_map assertion (`run_m3.py:42-52`) still guards the seq↔YYYYWW mapping.

**Watch for**: the sub-universe is 166 coins at end-2022 rising to 758 at end-2025.
Early weeks may fall below `signal.min_cross_section` (20) and be skipped; a skipped week
leaves the 52-week smoothing window incomplete and suppresses the next 52 emissions.
Log skipped weeks explicitly and report how many test weeks survive — if 2024 is thin,
say so rather than reporting a shorter series as if it were complete.

Runtime: ~2.5 min indicators + 3 s to_curated + ~5 min walk-forward ≈ **8 min**.

---

## Phase 2 — cheap post-processing (U2, U4)

Both operate on weekly series; neither touches `sorts.py`.

**U2 volatility targeting** — new `src/ctrend/portfolio/vol_target.py`.
`scale(returns, target_vol, lookback, max_leverage)` using **trailing** realized vol
(strictly data ≤ t−1), leverage capped. Grid for tuning: `target_vol ∈ {10, 15, 20}%`
annualised, `lookback ∈ {13, 26, 52}` weeks, `max_leverage ∈ {1.5, 2, 3}`.

**U4 beta hedge** — new `src/ctrend/portfolio/hedge.py`. Rolling causal beta of the long
leg on the market (reuse `mkt` from `m6_variants.csv`, and `factors.regress`
(`factors.py:100`) for the estimator), hedge ratio applied with a one-week lag; subtract
`β × market` and charge perpetual funding. Grid: `beta_lookback ∈ {26, 52}` weeks.
`CostsConfig.hedge` (`config.py:137,166`) is already declared and unused — fill that slot.

Runtime: seconds per configuration.

---

## Phase 3 — weight-level variants (U3, U6)

Both need position weights. `SortResult.weights` (`sorts.py:127`) is populated but **no
caller reads it**, and crucially returns are computed at `sorts.py:102` *before* weights
are stored — so rescaling post hoc changes nothing.

- **`portfolio/sorts.py`** — add an optional `weight_fn` hook applied between lines
  101 and 102, plus `prev_weights` passthrough so a transform can see last week's book.
- **U3 buffering**: keep a held coin until its rank leaves a wider band (enter top
  20%, exit only below 40%). Grid: `exit_pct ∈ {30, 35, 40}`. Also test EWMA-smoothed
  CTREND (`halflife ∈ {2, 4}` weeks) and 2/4-week holding.
- **U6 capacity cap**: cap each weight at `k × ADV / portfolio_size`, renormalise.
  Grid: `k ∈ {0.01, 0.05, 0.10}`.

**Turnover accounting must be recomputed consistently.** `_leg_turnover`
(`sorts.py:58-70`) normalises by `drifted.sum()`, which assumes fully-invested legs; a
capped or buffered book breaks that assumption, and `cost` (`sorts.py:121`) would
silently absorb leverage as trading. This is exactly what Phase 0's characterization
tests protect.

---

## Phase 4 — U5 selection stability

**`signal/engine.py:102`** — `sel = np.where(fit.theta > 0)[0]` becomes a persistence
rule: an indicator enters only after surviving `N` consecutive windows. Requires a small
rolling history on the state object; must stay causal. Grid: `N ∈ {2, 3, 4}`.

Cheapest to implement, but requires a **full walk-forward re-run per parameter value**
(~5 min each). Tune on the 82-week window with a short grid.

---

## Phase 5 — tuning harness, evaluation, reporting

**`src/ctrend/evaluation/tune.py`** — runs each grid on 202223–202352 only, selects by
Sharpe, writes `reports/frozen_params.json` with a hash of the grid and the window
bounds. **`src/ctrend/evaluation/upgrade_eval.py`** refuses to run if the requested
window overlaps the tuning window unless `--tuning` is passed, so the freeze is
mechanical rather than a matter of discipline.

Consolidate the three near-duplicate `kpis` implementations (`long_only.py:34`,
`short_only.py:41`, `perf_kpis.py:23`) into one shared function and have all three
import it.

**Multiple-testing treatment.** Primary statistic is the paired difference (F2). Report
for **all ten** configurations — not the best of them — in one table:

| statistic | why |
|---|---|
| raw one-sided p from the OLS t | matches GT-12; the paper's t = 4.22 is an OLS t |
| **Benjamini–Hochberg q at 0.10** | primary adjustment; configs are nested and share a signal, so strongly positively dependent — BH is valid under PRDS and far less brutal than Bonferroni at family size 10 |
| Bonferroni at α = 0.005 | assumption-free; every reviewer asks |
| Harvey–Liu–Zhu haircut Sharpe at **M = 10, 31, 316** | M=31 is the honest one for this protocol (10 configs + 21 tuning grid points); 316 is HLZ's literature-wide reference. None is "the" answer and the report says so |
| stationary-bootstrap SPA p-value | the only one that handles dependence *between* configurations; block length ~4 weeks, ~40 lines of numpy rather than adding `arch` for one function |

`n_grid_points_searched` is written mechanically by `tune.py`, never by hand, so the
haircut cannot be quietly understated. `stats.report_table()` **raises if any
configuration is missing** — there is no code path that emits a subset — and the
pre-registered MDE prints *above* the results table.

**Deliverable** `reports/upgrade_experiment.md`: baseline vs each upgrade vs stack, on
the frozen configuration, with full KPI tables (return, vol, Sharpe, Sortino, max DD,
DD duration, hit rate, skew, turnover, net-of-cost at 30/40/50 bps) for 2024–26, plus
the tuning-window results shown separately so the regime gap is visible.

---

## What must not break

`make test` stays green throughout (137 tests). Specifically untouched:

- `tests/golden/test_cenet_golden.py:57` — exact selection `{0,3,7,12,20}` (read-only per SPEC §5)
- `tests/test_golden_parity.py:95-104` — exact λ to 1e-12, exact nonzero list, IC 0.088
- `tests/test_no_lookahead.py` — 17 tests, bitwise identity under future noise
- `tests/test_smoke.py:83-107` — the eleven pinned config values

All variants are **new paths alongside** the gated baseline. `evaluation/gate.py` bands
(`gate.py:101-109`) are read-only per I3 — vol targeting moves Sharpe, buffering moves
turnover, hedging moves CMOM beta, and none of that may touch the baseline gate.

---

## Runtime

| phase | cost |
|---|---|
| 0 safety net | ~10 min (mostly writing) |
| 1 U1 re-estimation | ~8 min |
| 2 U2/U4 | seconds per config |
| 3 U3/U6 | ~1 min per config |
| 4 U5 | ~5 min per parameter value |
| 5 tuning + evaluation | ~30–45 min total |

**Whole experiment ≈ 1.5–2 hours**, no re-harvesting, no external API calls.

---

## Risks, ordered by how badly each could mislead

1. **U1 becomes a bet on BTC's bucket** (F1, verified). *Guardrail:* the 10% name cap as
   primary, `effective_n`/`top1_weight` reported per leg per week, uncapped VW and EW as
   robustness. Note U6 (ADV cap) does much the same job — C1+C6 is a natural pairing.
2. **Perp survivorship flatters U1** (F3, verified). *Guardrail:* snapshot, offboarding,
   declared leakage channel, bias direction stated.
3. **Underpowered null read as "nothing works"** (F2, verified). *Guardrail:* paired
   differences, pre-registered MDE printed above the results.
4. **Vol targeting flatters itself via unmodelled leverage cost.** Cost must include the
   `|k_t − k_{t−1}| × Σ|w_{t−1}|` leverage-rebalancing term, with a test that fails
   without it. Do **not** tune the target level — that is tuning leverage, which moves
   the mean mechanically. Tune `lookback_weeks` only.
5. **Funding sign error makes the hedge free-roll.** Invisible if wrong, and it converts
   a cost into a subsidy. *Guardrail:* pin the sign against one real BTCUSDT week with a
   known positive rate; report hedged results with and without funding credited.
6. **Silent universe corruption from the registry join** in `to_curated.py:99-105` — a
   coin whose unmasked `first_week` predates its shortable debut keeps the wrong
   `first_seen_week`, and `dataset.py:130` then discards its rows with no error.
   *Guardrail:* rebuild the registry from the masked panel and assert
   `panel.coin_id.nunique() == registry.coin_id.nunique()` as a hard failure.
7. **Buffer/EWMA/overlap silently changing the baseline.** *Guardrail:* Phase 0
   characterization tests, plus three separate bit-exact identity tests (`width=0`,
   `halflife=0`, `k=1`).
8. **Regime mismatch** — tuning window 3.5× stronger than test. Report both windows side
   by side, and report 2024/2025/2026 separately: a whole-period average conceals a sign
   flip, exactly as the rolling-Sharpe error in `reports/m6_decay_report.md` did.
9. **ADV is CMC reported volume**, materially inflated by wash trading for small caps, so
   a capacity cap calibrated on it is looser than reality. State capacity results as an
   **upper** bound, matching the existing convention.
10. **`ltw_factors.parquet` ends at 202314**, so CMOM beta and alpha-vs-LTW **cannot be
    computed on 2024–26**. Extend the series or report raw and market-relative
    performance only — and say which.
11. **The honest prior**: 0.52%/wk on the test window against a 1.41% breakeven. The goal
    is a small positive *net* edge, not restoring Sharpe 1.94. A null across all ten
    configurations is a legitimate result.
12. **Scope creep into the read-only surface.** Nothing here touches
    `configs/replication.yaml`, `tests/golden/`, or the bands at `gate.py:101-109`. If an
    upgrade appears to require it, that is a STOP, not an edit.

## The design pattern that makes this safe

Every new capability ships with an **identity default** and a test asserting that
default is **bit-exact** against current behaviour: `universe_mask=None`,
`buffer_width=0.0`, `halflife=0.0`, `overlap=1`, `n_consecutive=1`,
`participation=∞`, `stability_levels=(1,)`. That is what allows six upgrades to be added
to a codebase with numerically pinned tests (exact λ to 1e-12, exact selection sets)
without breaking a single pin.

---

## Verification

1. `make test` green after every phase.
2. U1 sanity: assert the emitted universe contains only coins with `onboard_week <= week`;
   confirm week counts and cross-section sizes per year.
3. Baseline reproducibility: re-running the unmodified path must reproduce
   `reports/baseline_m6_variants.csv` exactly.
4. Freeze integrity: `upgrade_eval.py` must refuse a tuning-window run without the flag;
   verify `frozen_params.json` is written before any test-window evaluation.
5. No-look-ahead: the existing 17-test suite must pass against the U1 curated panel too.
