# Upgrade experiment — results

Date: 2026-07-19 · revised **2026-07-21** · 177 tests green · artefacts
`reports/upgrades_evaluation.csv`, `configs/frozen_params.json`
(sha256 `d2bfa8363dd1…`)

> ### Correction note — 2026-07-21
>
> An adversarial audit of this repository confirmed several defects in the
> 2026-07-19 version of this document. The experiment was re-run with DuckDB row
> ordering pinned; what follows is the corrected record. **Retracted or changed:**
>
> 1. **SPA p-value 0.643 → 0.726.** The old value was irreproducible: `harness.load_panel`
>    issued an unordered `SELECT` under `PRAGMA threads=4`, so float summation order
>    varied per run and re-runs returned 0.221–0.877. With `ORDER BY` pinned the value
>    is stable at **0.726**.
> 2. **C4 is removed from the test family.** C4's difference from baseline is *exactly*
>    zero — bit-exact, every run. The previously reported `t = 0.74` was 100% rounding
>    noise from the same ordering bug (across runs it wandered −2.25, −0.20, +0.08,
>    +0.72, +1.63, +2.19). `paired_t`'s zero-variance guard now fires: C4 has no t, no p,
>    no q, no haircut. **The family is 8 tests, not 10;** Bonferroni and BH now run on 8.
> 3. **The C4 beta claim is withdrawn in full.** The old text said the H−L spread's
>    "mean beta 0.0048" independently reproduced the paper's βCMKT ≈ 0.03. That was
>    wrong three ways (see *C4* below). The spread's true out-of-sample market beta is
>    about **−0.5**. It is *not* market-neutral out of sample.
> 4. **The Harvey–Liu–Zhu haircut is a saturation artefact, not a finding.** `stats.py`
>    clips the adjusted p at 1−1e−12, so *any* p_raw > 0.10 zeroes the haircut Sharpe for
>    *any* Sharpe however large. The haircut also now rescales the **paired-difference**
>    Sharpe by the paired-difference t (the actual HLZ procedure); it previously rescaled
>    the *level* Sharpe. M is now the number of tests performed (8), not `len(table)` (10,
>    which wrongly counted the baseline as a test).
> 5. **"Nothing is close" is withdrawn.** C8 reaches 81% and C9 85% of their own
>    pre-registered bands. The defensible statement is that **no configuration clears its
>    threshold**.
> 6. **The pre-registered MDEs are ex-ante, not this window's power.** They were estimated
>    on the 82-week 2022–23 tuning window (a 3.5× stronger regime) and divided by √133 for
>    every config, including those where fewer weeks survive. Realized evaluation-window
>    thresholds are now reported beside them and differ materially (C7 1.55 → 2.80,
>    C8 1.54 → 2.94).
> 7. **The feasibility-mask bound was stated backwards.** It was called an *upper* bound on
>    shortability; both named mechanisms bias it **down**. See *Caveats*.
> 8. **"A BTC bet" is withdrawn.** Deleting Bitcoin entirely leaves the uncapped C1 variant
>    at +0.248%/wk (82% of +0.301), and the cap still flips the sign. It is a
>    **concentration** bet, not a Bitcoin bet.
>
> Every other configuration's numbers are unchanged to three decimals. The freeze held:
> re-running tuning selected identical parameters and byte-identical MDEs; only the 16th
> significant digit of `vol_target` moved.

**Protocol.** Parameters were fitted on **202223–202352 (82 weeks)** only, frozen with an
integrity hash, and the configurations evaluated **once** on **202401–202629 (133 weeks)**.
15 grid points searched. The evaluation entry point exposes no parameter arguments, so
re-tuning from it is structurally impossible.

**Pre-registered ex-ante minimum detectable effect** (paired difference, Bonferroni, 80%
power), written to the frozen file *before* the evaluation was read. These were estimated
on the **2022–23 tuning window** and scaled by √133 uniformly; they are a statement of
what we committed to detect, not of this window's realized power. The realized column
recomputes the same threshold on the evaluation window itself:

| config | ex-ante MDE %/wk | realized %/wk | config | ex-ante MDE %/wk | realized %/wk |
|---|---|---|---|---|---|
| C1 shortable+cap | 1.77 | 1.51 | C6 capacity | 1.65 | 1.89 |
| C2 vol-target | 0.40 | 0.75 | C7 C1+C6 | 1.55 | 2.80 |
| C3 turnover | 0.47 | 0.69 | C8 stack | 1.54 | 2.94 |
| C5 stability | 0.49 | 0.66 | C9 stack+hedge | 1.58 | 2.45 |

The pre-registered number is the one that binds — that is the point of pre-registration —
but where the realized threshold is nearly twice the frozen one (C7, C8) the frozen band
overstates what these 133 weeks could actually see. **C4 carried a frozen MDE of 0.04%/wk
and is now excluded from the family** (its difference is identically zero, so no test is
defined); that band is reported for the record only.

Frozen parameters: `vol_lookback 52 · buffer 0.10 · stability_n 3 · beta_window 52 ·
vol_target 0.348`, selected on net Sharpe at 55bps over the tuning window.

---

## RESULT: no upgrade improves the strategy. None clears its own threshold.

Evaluation window 202401–202629. `tune` is the same configuration's mean over the
202223–202352 fitting window, shown for transfer, **not** for selection.

| config | n | mean %/wk | Sharpe | max DD | hit % | diff vs base | t | q(BH) | Bonf | tune %/wk |
|---|---|---|---|---|---|---|---|---|---|---|
| **C0 baseline** | 133 | 0.522 | 0.500 | −62.1 | 61.7 | — | — | — | — | 1.854 |
| C1 shortable+cap | 125 | **−0.292** | −0.381 | −66.4 | 53.6 | **−0.860** | −1.95 | 0.973 | ✗ | −0.598 |
| C2 vol-target | 133 | 0.256 | 0.340 | **−49.2** | 61.7 | −0.266 | −1.22 | 0.973 | ✗ | 1.689 |
| C3 turnover | 133 | 0.530 | 0.548 | −55.6 | 59.4 | +0.008 | 0.04 | 0.973 | ✗ | 1.496 |
| ~~C4 beta-hedge~~ | 133 | 0.522 | 0.500 | −62.1 | 61.7 | 0.000 (exact) | — | — | — | 1.873 |
| C5 stability | 133 | **0.611** | **0.594** | −52.2 | 61.7 | **+0.089** | 0.46 | 0.973 | ✗ | 1.837 |
| C6 capacity | 133 | 0.503 | **0.609** | **−48.3** | 53.4 | −0.019 | −0.03 | 0.973 | ✗ | 1.203 |
| C7 C1+C6 | 125 | −0.296 | −0.399 | −56.0 | 48.0 | −0.864 | −1.06 | 0.973 | ✗ | −0.116 |
| C8 stack | 121 | −0.751 | −0.955 | −70.8 | 47.9 | −1.243 | −1.45 | 0.973 | ✗ | −0.332 |
| C9 stack+hedge | 121 | −0.850 | −1.173 | −74.8 | 49.6 | −1.342 | −1.88 | 0.973 | ✗ | −0.353 |

C4 is struck through because it is a **bit-exact no-op**: its weekly series is identical
to the baseline's to the last bit, so the paired difference has zero variance and no test
statistic exists. It contributes no t, no p, no q and no haircut, and it is **not** counted
in the family. *The family is 8 tests.* (The 2026-07-19 version reported `t = 0.74` for
this row; that figure was floating-point summation noise and is retracted.)

**SPA p-value (best configuration genuinely beats the baseline): 0.726**, stable across
re-runs now that row ordering is pinned. Zero Bonferroni passes; every BH q-value is
0.973 across the 8 tests.

On the Harvey–Liu–Zhu haircut: the two positive-difference configurations (C3, C5) have
haircut difference-Sharpes of zero to 11 decimals at M = 8, M = 31 and M = 316. **This
carries almost no information and the earlier reading of it is retracted.** `stats.py`
clips the adjusted p at 1 − 1e−12, so *any* raw p above roughly 0.10 collapses the
adjusted t to ~0 and the haircut Sharpe to ~0 regardless of how large the underlying
Sharpe is. The correct statement is the trivial one: **no positive difference has
p_raw below 0.10, so any multiple-testing haircut at M ≥ 8 zeroes it.** The haircut now
rescales the paired-**difference** Sharpe by the paired-difference t; the previous version
rescaled the *level* Sharpe by the difference's t, which is not the HLZ procedure.

---

## What each result actually means

### C1 — the shortable universe is *worse*, and this is the most informative result

Restricting to coins with a live perpetual and re-estimating inside that universe gives
**−0.29%/wk versus +0.52% for the baseline** — a paired difference of −0.86%/wk with
t = −1.95, i.e. the closest anything came to significance, in the wrong direction.

The name cap did exactly what it was pre-registered to do:

| | top-1 weight | effective N | mean %/wk |
|---|---|---|---|
| uncapped | 0.629 | 3.45 | +0.301 |
| **capped at 10%** | 0.100 | **31.6** | **−0.292** |

The concentration figures above are **long-leg only**; the short leg is far more diffuse
(top-1 0.292, effective N 12.19). The earlier version omitted that label.

So the uncapped version's mild positive return **was a concentration bet** — capping
concentration turned +0.30%/wk into −0.29%/wk. It was **not**, as the 2026-07-19 version
claimed, *a Bitcoin bet*, and that claim is retracted. Deleting BTC from the universe
entirely still leaves the uncapped variant at **+0.248%/wk, 82% of the +0.301%/wk**; BTC
is the top-1 holding in only 69 of 125 weeks; and the cap flips the sign even with BTC
removed. The return does not come from one named coin — it comes from *whichever* handful
of names happens to dominate the long book in a given week, and it does not survive being
spread across more of them. Had this been run paper-faithfully without the cap, it would
have been reported as the one upgrade that "worked", and it would have been an artefact of
an effective breadth of 3.45 names.

And this is not a 2024–26 regime artefact. C1 is the **only** configuration that was
also negative in the tuning window (−0.60%/wk while the baseline made +1.85%/wk there).
Every other upgrade at least made money in 2022–23. The shortable universe fails in both
regimes, three and a half years apart.

The interpretation is uncomfortable but clean: **CTREND's cross-sectional signal does not
work inside the tradable universe.** The information it exploits lives in the small,
illiquid names at the edge of the panel; making the strategy implementable removes the
thing that made it profitable.

*Corrected mechanism.* The 2026-07-19 version attributed this to the premium sitting in
"a short leg that could not be traded". Both halves of that are wrong and are retracted.
(i) On **raw** returns the long leg supplied **97%** of the in-sample premium (+3.794 of
3.894%/wk) and then collapsed by 85% out of sample (+3.794 → +0.585%/wk); the short leg
went +0.101 → +0.445%/wk. The old "premium is in the short leg" reading came from silently
quoting the *market-relative* decomposition (long +1.855 / short +2.039 in sample) as
though it were raw returns. The market-relative split is not wrong, but it cannot be used
to argue about tradability. **It is the long leg — the tradable side — that failed.**
(ii) The short book was not untradable out of sample: by market-cap weight, which is what
matters for a value-weighted book, **53.1%** of the short leg was shortable out of sample
and 62.0% over the last 52 weeks (headcount 14.7% and 26.3%). C1 fails despite the
tradable universe being substantially available, not because it was unavailable.

### C4 — a no-op, but for the opposite reason to the one previously given

Mean, Sharpe and max drawdown are identical to baseline — not to three decimals but
**bit-exactly**, in all 133 weeks.

**The previous explanation of this is wrong in full and is retracted.** The 2026-07-19
version reported a "mean beta of 0.0048, exceeding 0.01 in only 10 of 133 weeks",
concluded the spread was "already market-neutral", and claimed this "independently
reproduces the paper's βCMKT = 0.03". Three separate errors:

1. **0.0048 is not a market beta.** It is a *zero-floored hedge ratio*
   (`overlays.py`, `beta_min = 0.0`) — an estimate that has already been clipped at zero
   from below.
2. **It came from a discarded tuning candidate.** That figure only arises at
   `beta_window = 26`. At the **frozen** `beta_window = 52` the clipped hedge ratio is
   exactly 0.000000 and exceeds 0.01 in **0 of 133 weeks**. The "10 of 133 weeks" and the
   "+0.0009%/wk funding" figures are `bw = 26` artefacts and do not describe the
   configuration that was actually evaluated.
3. **The spread's real beta has the opposite sign and is large.** Over the evaluation
   window the H−L spread's market beta is strongly **negative**: rolling mean **−0.468**,
   static OLS **−0.535**.

**Correct statement:** C4 is a no-op because the hedge ratio's non-negativity floor
(`beta_min = 0`) binds in all 133 weeks — the estimated beta is about −0.5, the floor
clips it to zero, and the overlay therefore trades nothing. **The spread is not
market-neutral out of sample; it is materially short the market.** Any claim that this
experiment reproduces the paper's βCMKT is withdrawn.

Because the difference from baseline is identically zero, C4 supports no inference at all:
it is not a well-powered null, it is the absence of a test. Its frozen 0.04%/wk MDE is
retained only as a record of what was pre-registered. A genuine hedge test would require
lifting `beta_min` below zero, which the freeze does not permit and which is left to
future work.

### C5, C6 — small, real risk improvements that do not reach significance

C5 (require an indicator to survive 3 consecutive windows) gives the best point estimate:
+0.089%/wk, Sharpe 0.594 vs 0.500, drawdown −52.2% vs −62.1%. C6 (capacity cap at $50M,
1% ADV) gives the best Sharpe (0.609) and shallowest drawdown (−48.3%) at essentially
unchanged mean. Both are consistent with genuine but modest risk-side improvements — and
with a pre-registered MDE of 0.49%/wk for C5 (0.66%/wk realized on this window), an effect
of 0.089%/wk is far below what 133 weeks can resolve. **Not evidence of nothing; evidence
that we cannot tell.**

### C2 — vol targeting cut drawdown 13 points and cost return

−62.1% → −49.2% drawdown, mean 0.522 → 0.256. The leverage-rebalancing cost term is
included; without it the overlay would have looked free.

### C8/C9 — stacking compounds the damage

Both stacks are strongly negative, dominated by C1's universe restriction. Interactions
are not additive and the stack is one draw from one ordering.

---

## Honest reading

**Where the experiment was powered, it returns clean nulls** (C3 and C5, whose realized
thresholds of 0.69 and 0.66%/wk are close to their frozen bands and comfortably above
their +0.008 and +0.089%/wk effects). **Where it was underpowered — C1, C6, C7, C8, C9,
at frozen bands of 1.54–1.77%/wk and realized thresholds up to 2.94%/wk — no conclusion
about small effects is available**, and the pre-registered MDEs above are why that
limitation was stated before the numbers were read rather than after. C4 provides no
information in either direction: its difference is identically zero, so it was never a
test (see above). *The earlier claim that C4 was the experiment's most decisively powered
null is retracted.*

The claim that "nothing is close" is also retracted. Two configurations get within
striking distance of their own pre-registered bands — **C8 at 81%** (−1.243 vs 1.539) and
**C9 at 85%** (−1.342 vs 1.581) — though both in the *wrong* direction, and both against
realized thresholds roughly twice as large. The supportable statement is narrower and
still sufficient: **no configuration clears its own threshold, in either direction.**

The headline does not depend on power. C1 is *negative*, near-significantly so, and the
mechanism is identified and measured: concentration capping flips the sign, so the
uncapped gain was an effective breadth of three and a half names. The strategy's edge and
its tradability are inversely related.

**Nothing here rescues CTREND out of sample.** The best available configuration on this
evidence is C5 or C6 — modest drawdown and Sharpe improvements on a strategy whose mean
return, 0.52%/wk frictionless, still sits below its own 1.41% breakeven transaction cost.

## Caveats carried forward

* **The direction of the feasibility-mask bound was stated backwards and is corrected
  here.** The 2026-07-19 version called C1's universe an **upper** bound on what was
  shortable, "which makes its negative result, if anything, generous". That is the wrong
  way round. `exchangeInfo` survivorship means a coin that *had* a perp and was later
  fully delisted is absent from the snapshot and reads as never-shortable — which can only
  **shrink** the shortable set. Perps are also not the only short venue (margin borrow and
  OTC existed), which biases the same way. The one channel biasing the mask **up** is that
  shortability is assigned by a bare **ticker** match
  (`feasibility_mask.py` joins `upper(perp.base) = panel.sym`): ~145 perp tickers are
  shared by ~342 panel coins, so up to ~197 coins may be marked shortable purely by ticker
  collision — deduplicating to the largest coin per ticker drops the out-of-sample
  headcount share from 14.7% to 13.6%. The mask is therefore bounded in **both**
  directions and is **not exact**; no directional generosity should be read into C1's
  negative result. (Three `PENDING_TRADING` contracts that never traded are now excluded
  and the onboard/offboard predicate is applied as an interval rather than a half-line,
  which moved the headcount shares slightly: 0.95 → 0.94% in sample, 14.75 → 14.69% out.)
* ADV comes from CMC reported volume, inflated by wash trading for small caps, so C6's
  capacity constraint is looser than reality.
* `ltw_factors.parquet` ends at 202314, so CMOM beta and alpha-vs-LTW cannot be computed
  on this window. Performance here is raw and market-relative only.
* The tuning window (baseline 1.85%/wk) is a 3.5× stronger regime than the evaluation
  window (0.52%/wk). Parameters chosen there — a 52-week vol lookback, a 34.8% vol
  target — were selected against a volatility level the evaluation window does not
  share, so C2's return give-up is partly a transfer failure rather than a property of
  vol targeting.
* The pre-registered MDEs were computed from the standard deviation of the **82-week
  2022–23 tuning window** and divided by √133 for every configuration, including C1, C7,
  C8 and C9 where only 121–125 weeks survive. They are ex-ante commitments, not a measure
  of this window's power; realized thresholds are tabulated beside them above and are up
  to 1.9× larger.
* Nine configurations evaluated, of which **eight are tests** — C4's difference is
  identically zero and carries no statistic. One baseline, one evaluation, no re-runs.
  But the six upgrades themselves were chosen after seeing the 2024–26 decay in the M6
  report. That selection step is not captured by any of the corrections above; it is the
  reason the HLZ haircut is also reported at M = 31 and M = 316 — though as noted, the
  haircut saturates for any p_raw > 0.10 and so distinguishes little between those M.
* The 2026-07-19 run was not reproducible: `harness.load_panel` issued an unordered
  `SELECT` under `PRAGMA threads=4`, so float summation order varied between runs. This
  was harmless for every configuration except C4, whose true difference is exactly zero
  and for which the noise was therefore 100% of the signal. Ordering is now pinned with an
  explicit `ORDER BY` and the SPA p-value is stable at 0.726. The freeze itself held:
  re-tuning selected identical parameters and byte-identical MDEs, with only the 16th
  significant digit of `vol_target` differing.
