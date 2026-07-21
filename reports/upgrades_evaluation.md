# Upgrade experiment — results

Date: 2026-07-19 · 177 tests green · artefacts `reports/upgrades_evaluation.csv`,
`configs/frozen_params.json` (sha256 `6ee6c73db6dc…`)

**Protocol.** Parameters were fitted on **202223–202352 (82 weeks)** only, frozen with an
integrity hash, and the configurations evaluated **once** on **202401–202629 (133 weeks)**.
15 grid points searched. The evaluation entry point exposes no parameter arguments, so
re-tuning from it is structurally impossible.

**Pre-registered minimum detectable effect** (paired difference, Bonferroni, 80% power),
written to the frozen file *before* the evaluation was read:

| config | MDE %/wk | config | MDE %/wk |
|---|---|---|---|
| C1 shortable+cap | 1.77 | C5 stability | 0.49 |
| C2 vol-target | 0.40 | C6 capacity | 1.65 |
| C3 turnover | 0.47 | C7 C1+C6 | 1.55 |
| **C4 beta-hedge** | **0.04** | C8 / C9 stack | 1.54 / 1.58 |

Frozen parameters: `vol_lookback 52 · buffer 0.10 · stability_n 3 · beta_window 52 ·
vol_target 0.348`, selected on net Sharpe at 55bps over the tuning window.

---

## RESULT: no upgrade improves the strategy. Nothing is close.

Evaluation window 202401–202629. `tune` is the same configuration's mean over the
202223–202352 fitting window, shown for transfer, **not** for selection.

| config | n | mean %/wk | Sharpe | max DD | hit % | diff vs base | t | q(BH) | Bonf | tune %/wk |
|---|---|---|---|---|---|---|---|---|---|---|
| **C0 baseline** | 133 | 0.522 | 0.500 | −62.1 | 61.7 | — | — | — | — | 1.854 |
| C1 shortable+cap | 125 | **−0.292** | −0.381 | −66.4 | 53.6 | **−0.860** | −1.95 | 0.973 | ✗ | −0.598 |
| C2 vol-target | 133 | 0.256 | 0.340 | **−49.2** | 61.7 | −0.266 | −1.22 | 0.973 | ✗ | 1.689 |
| C3 turnover | 133 | 0.530 | 0.548 | −55.6 | 59.4 | +0.008 | 0.04 | 0.973 | ✗ | 1.496 |
| C4 beta-hedge | 133 | 0.522 | 0.500 | −62.1 | 61.7 | +0.000 | 0.74 | 0.973 | ✗ | 1.873 |
| C5 stability | 133 | **0.611** | **0.594** | −52.2 | 61.7 | **+0.089** | 0.46 | 0.973 | ✗ | 1.837 |
| C6 capacity | 133 | 0.503 | **0.609** | **−48.3** | 53.4 | −0.019 | −0.03 | 0.973 | ✗ | 1.203 |
| C7 C1+C6 | 125 | −0.296 | −0.399 | −56.0 | 48.0 | −0.864 | −1.06 | 0.973 | ✗ | −0.116 |
| C8 stack | 121 | −0.751 | −0.955 | −70.8 | 47.9 | −1.243 | −1.45 | 0.973 | ✗ | −0.332 |
| C9 stack+hedge | 121 | −0.850 | −1.173 | −74.8 | 49.6 | −1.342 | −1.88 | 0.973 | ✗ | −0.353 |

**SPA p-value (best configuration genuinely beats the baseline): 0.643.** Zero
Bonferroni passes; every BH q-value is 0.973. The Harvey–Liu–Zhu haircut is total —
for the three positive-difference configurations (C3, C4, C5) the haircut Sharpe is
zero to 11 decimals at M = 10, and stays zero at M = 31 and M = 316. Under any
plausible accounting of how many strategies were tried, none of these differences
carries information.

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

So the uncapped version's mild positive return **was** a BTC bet: capping concentration
turned +0.30%/wk into −0.29%/wk. Had this been run paper-faithfully without the cap, it
would have been reported as the one upgrade that "worked", and it would have been an
artefact of a single coin's bucket assignment.

And this is not a 2024–26 regime artefact. C1 is the **only** configuration that was
also negative in the tuning window (−0.60%/wk while the baseline made +1.85%/wk there).
Every other upgrade at least made money in 2022–23. The shortable universe fails in both
regimes, three and a half years apart.

The interpretation is uncomfortable but clean: **CTREND's cross-sectional signal does not
work inside the tradable universe.** The information it exploits lives in the small,
illiquid, unshortable names — which is precisely why the earlier feasibility analysis
found the premium concentrated in a short leg that could not be traded. Making the
strategy implementable removes the thing that made it profitable.

### C4 — a perfect no-op, and correctly so

Mean, Sharpe and max drawdown are identical to baseline to three decimals. The estimated
beta of H−L on the market averages **0.0048**, exceeding 0.01 in only 10 of 133 weeks.
The H−L spread is *already* market-neutral, which independently reproduces the paper's
own Table 3 finding (βCMKT = 0.03). Funding contributed +0.0009%/wk.

With an MDE of 0.04%/wk this is a **well-powered null**: the hedge genuinely has nothing
to hedge, rather than the test being unable to see it.

### C5, C6 — small, real risk improvements that do not reach significance

C5 (require an indicator to survive 3 consecutive windows) gives the best point estimate:
+0.089%/wk, Sharpe 0.594 vs 0.500, drawdown −52.2% vs −62.1%. C6 (capacity cap at $50M,
1% ADV) gives the best Sharpe (0.609) and shallowest drawdown (−48.3%) at essentially
unchanged mean. Both are consistent with genuine but modest risk-side improvements — and
with an MDE of 0.49%/wk for C5, an effect of 0.089%/wk is far below what 133 weeks can
resolve. **Not evidence of nothing; evidence that we cannot tell.**

### C2 — vol targeting cut drawdown 13 points and cost return

−62.1% → −49.2% drawdown, mean 0.522 → 0.256. The leverage-rebalancing cost term is
included; without it the overlay would have looked free.

### C8/C9 — stacking compounds the damage

Both stacks are strongly negative, dominated by C1's universe restriction. Interactions
are not additive and the stack is one draw from one ordering.

---

## Honest reading

**Where the experiment was powered, it returns clean nulls** (C4 decisively, C3 and C5
nearly). **Where it was underpowered — C1, C6, C7, C8, C9 at MDEs of 1.54–1.77%/wk — no
conclusion about small effects is available**, and the pre-registered MDEs above are why
that limitation was stated before the numbers were read rather than after.

But the headline does not depend on power. C1 is *negative*, near-significantly so, and
the mechanism is identified and measured: concentration capping flips the sign, so the
uncapped gain was one coin. The strategy's edge and its tradability are inversely
related.

**Nothing here rescues CTREND out of sample.** The best available configuration on this
evidence is C5 or C6 — modest drawdown and Sharpe improvements on a strategy whose mean
return, 0.52%/wk frictionless, still sits below its own 1.41% breakeven transaction cost.

## Caveats carried forward

* The feasibility mask remains survivorship-biased (`exchangeInfo` returns only live
  contracts). 123 of 125 non-trading contracts now carry a bounded interval, but fully
  removed ones are invisible. C1's universe is an **upper** bound on what was shortable,
  which makes its negative result, if anything, generous.
* ADV comes from CMC reported volume, inflated by wash trading for small caps, so C6's
  capacity constraint is looser than reality.
* `ltw_factors.parquet` ends at 202314, so CMOM beta and alpha-vs-LTW cannot be computed
  on this window. Performance here is raw and market-relative only.
* The tuning window (baseline 1.85%/wk) is a 3.5× stronger regime than the evaluation
  window (0.52%/wk). Parameters chosen there — a 52-week vol lookback, a 34.8% vol
  target — were selected against a volatility level the evaluation window does not
  share, so C2's return give-up is partly a transfer failure rather than a property of
  vol targeting.
* Nine configurations, one baseline, one evaluation, no re-runs. But the six upgrades
  themselves were chosen after seeing the 2024–26 decay in the M6 report. That selection
  step is not captured by any of the corrections above; it is the reason the HLZ haircut
  is also reported at M = 316.
