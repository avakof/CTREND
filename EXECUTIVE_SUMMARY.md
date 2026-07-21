# CTREND — Executive Summary

Replication and out-of-sample extension of Fieberg, Liedtke, Poddig, Walker &
Zaremba, *A Trend Factor for the Cross Section of Cryptocurrency Returns*,
JFQA 60 (2025), 3116–3153.

2026-07-19 · **corrected 2026-07-21** · 177 tests green · full detail in
`validation_report.md` and `reports/m6_decay_report.md`.

Six candidate repairs were subsequently tested under pre-registration, in **nine
configurations** (the six single upgrades plus three stacks). One (a beta hedge) turned
out to be a bit-exact no-op and is excluded, leaving a family of **eight** tests; none
survives multiple-testing correction — see `reports/upgrades_evaluation.md`.

> **Correction, 2026-07-21.** An adversarial audit of this repository confirmed 34
> defects, several of which touched this document. The substantive ones, all now fixed
> below:
>
> 1. **The leg decomposition was market-relative, presented as raw.** The old text said
>    the legs "contributed roughly equally (1.85% and 2.04%/week)" in sample and that
>    "85% of what remains comes from shorting the bottom quintile" out of sample. Those
>    are the *market-relative* legs (q5 − mkt and mkt − q1). On **raw** returns the long
>    leg supplied **97%** of the in-sample premium and then collapsed by 85%. The thesis
>    that "the surviving premium sits in the short leg" **is retracted in raw terms**.
> 2. **The Binance perp mask is not an "exact" record of shortability**, and the
>    headcount share understated tradability. Every return here is value-weighted, so the
>    market-cap-weighted share is the relevant one: **53.1%** of the out-of-sample short
>    book by weight was shortable, not 14.7%. The claim that the surviving edge sits in
>    a book that "cannot be traded" **is retracted**.
> 3. **Variant B was misstated** as 0.61%/wk (t 1.06); regenerated it is 0.684%/wk
>    (t 1.20). Still insignificant.
> 4. **"Means differ by 0.04 pp" was attributed to the wrong comparison** (3.945 − 3.87
>    = 0.075). The 0.04 pp gap is against the authors' shipped series over the 353
>    overlapping weeks.
> 5. **Quoting only Spearman 0.818 was selective** — Pearson on the same weeks is 0.627.
> 6. **The paper's window was mis-dated** as Apr 2015 – May 2022; it is Mar 2015 – Jun
>    2022 (Liu weeks 201510–202222).
> 7. **A beta claim is deleted outright.** The spread was said to reproduce the paper's
>    β_CMKT ≈ 0.03. It does not; its out-of-sample beta is about **−0.5**. See below.
> 8. **The upgrade family was 10 tests, counting the baseline and a no-op.** It is
>    **eight**. The SPA p-value was irreproducible (0.643, re-runs 0.221–0.877) because
>    of unordered DuckDB row summation; pinned, it is **0.726**. No conclusion changes.
>
> The decay itself, the replication, and the upgrade-experiment null are unchanged.

---

## The replication succeeds. The strategy does not survive out of sample at an implementable magnitude.

**We reproduced the paper.** Over its own window (Mar 2015 – Jun 2022, Liu weeks
201510–202222) all **seven** immutable SPEC §7 acceptance bands pass: H−L
**3.945%/week** (paper 3.87), Sharpe **1.620** (1.94), CMOM beta **0.771** (0.79),
alpha vs LTW **2.94%** with t **3.42**, turnover **70.1%** (68.45). Against the authors'
own published factor series our reconstruction correlates at **Spearman 0.818** /
**Pearson 0.627** with **84.1%** weekly sign agreement, and over the 353 overlapping
weeks the two means differ by **0.04 pp** (3.945 vs their 3.989). Net-of-cost returns
land on the paper's Table 9 almost exactly (2.95 / 2.67 / 2.39 vs 2.90 / 2.62 / 2.35),
and breakeven transaction cost matches at **1.41%**. None of this was calibrated; the
bands were fixed before any result was computed.

Three caveats on the word "reproduced", all previously understated. The 0.04 pp figure
is against the authors' *shipped series*, not against their Table 3 headline of 3.87%
(that gap is 0.075 pp, and their full 371-week series means 3.866%). The comparison uses
353 of their 371 published weeks. And the §7 bands are not the only pre-registered
gates: the M1 sample gate **failed** (14/40 cells) and the factor-reconstruction gate
cleared 0.95 only for CMKT (0.954) — CSMB 0.511 and CMOM 0.723 did not. The replication
**succeeds**; it is not perfect.

**Extended to today (215 genuinely out-of-sample weeks, to July 2026), it decays by
73%** — from 3.89%/week to **1.03%/week**. The frictionless spread stays statistically
significant (t = 2.27) but at roughly a quarter of its historical size. (The in-sample
block is 354 of 377 calendar weeks — 23 lack a valid cross-section, all in 2015–16; the
out-of-sample block is 215 of 215, though the final week 202629 is a 3-day stub.)

**Every implementable version loses significance:**

| | in-sample | out-of-sample |
|---|---|---|
| paper-faithful H−L | 3.89%/wk (t 4.17) | **1.03%/wk** (t 2.27) |
| short book restricted to what could be shorted | 2.92%/wk (t 1.50, n=56) | **0.68%/wk** (t 1.20, n=205) |
| long-only, top-half liquidity | 3.69%/wk (t 4.00) | **0.53%/wk** (t 1.00) |

**Why: the long leg — the tradable side — is what collapsed.** This is the correction
that most changes the story. The premium decomposes two ways, and they say opposite
things:

| | in-sample (354 wks) | out-of-sample (215 wks) |
|---|---|---|
| H−L | 3.894%/wk (t 4.17) | 1.030%/wk (t 2.27) |
| **raw** long leg (q5) | **+3.794** — 97% of H−L (t 3.66) | **+0.585** — 57% (t 1.14) |
| **raw** short leg (−q1) | +0.101 — 3% (t 0.14) | +0.445 — 43% (t 0.63) |
| market (mkt) | +1.939 | +0.438 |
| market-relative long (q5 − mkt) | +1.855 — 48% | +0.148 — 14% |
| market-relative short (mkt − q1) | +2.039 — 52% | +0.882 — 86% |

Earlier versions of this summary quoted the bottom two rows — 1.85%/2.04% in sample,
"85% from the short leg" out of sample — while describing them as returns. They are
market-relative excesses. **In raw terms the long leg supplied 97% of the in-sample
premium and then lost 85% of it (3.794 → 0.585%/week).** The claim that the surviving
edge sits in the short leg is **withdrawn as a statement about raw returns**; it holds
only after netting out the market, which is not the quantity a trader earns. The
market-relative view is not wrong, but it cannot be used to argue about tradability.

Neither out-of-sample leg is individually significant (t 1.14 and t 0.63). The spread
survives on the difference, not on either side.

**Shortability was understated.** Using Binance perpetual onboarding dates: only
**11.9%** of the 6,861 coins in our panel ever had a perpetual, and the first contract
onboarded in **September 2019** — the strategy's short book was 0%-shortable for the
**4.71 years** from 2015-03-11 to 2019-11-25. But every return here is value-weighted,
so the headcount share is the wrong denominator:

| | headcount | market-cap weight |
|---|---|---|
| paper window | 0.94% | **11.37%** |
| out-of-sample | 14.69% | **53.09%** |
| last 52 weeks | 26.34% | **62.01%** |

Out of sample the **majority of the short book by dollar weight was shortable**. The
earlier statement that the surviving premium sits in a leg that "cannot be traded" is
**retracted**. What remains true is that restricting the short book to feasible names
still leaves an insignificant 0.68%/week (t 1.20).

This mask is **not** an exact record, and we previously called it one. It is bounded on
both sides. Two mechanisms bias it *down*: `exchangeInfo` survivorship (a coin that had
a perp and was later fully delisted reads as never-shortable), and perps not being the
only venue (margin borrow and OTC existed). One biases it *up*: shortability is assigned
by bare ticker match, and ~145 perp tickers are shared by ~342 panel coins, so up to
~197 coins may be marked shortable on a collision. Deduplicating to the largest coin per
ticker moves the out-of-sample headcount share from 14.7% to 13.6%.

**Timing — unstable, not a smooth decline.** By calendar year the frictionless spread
returned +187% (2023), **−41.9% with a 59.8% drawdown (2024)**, **+166.4% (2025)**, and
−14.2% in 2026 to date. The 1.03%/week out-of-sample average is the mean of wildly
dispersed annual outcomes, not a stable reduced edge. Note the worst year *precedes*
the paper's 2025 publication, which weakens a simple "arbitraged-away" reading.

**The tradable version lost money even in the good year.** In 2025 the frictionless
spread returned +166.4% while long-only-within-liquid-names returned **−13.0%**, and
**−27.6%** net of 50/60 bps. In 2026 to date: −35.2% and −41.6% net.

**One reading is kinder.** Volatility fell from 17.6% to 6.7% weekly, so the Sharpe
(1.12) degrades far less than the mean. A volatility-targeting investor would see a
milder deterioration than the raw spread implies.

---

## What to trust, and what not to

**Reliable:** the in-sample replication. It matches the authors' own factor week by
week, not merely on average, and reproduces their cost table and breakeven figure
independently. Rank agreement is much stronger than level agreement (Spearman 0.818,
Pearson 0.627) and our reconstruction is the more volatile of the two (weekly SD 17.57%
vs 14.40%, Sharpe 1.620 vs 1.997), so trust it as a reproduction of the *signal*, less
so of the exact magnitudes.

**Solid but caveated:** the out-of-sample decay. It rests on a panel rebuilt from CMC
daily snapshots, since the authors' replication package ships **MATLAB code only, no
data**. Our universe runs ~16% larger than theirs from 2018 onward because CMC has
backfilled its history since 2022 — a documented failure of the M1 sample gate
(14/40 cells) that we deliberately did **not** tune away.

**The main residual limitation:** high/low data is missing for ~5% of coin-weeks,
concentrated in delisted coins, which biases the short leg. The short leg carries 43% of
the surviving out-of-sample premium in raw terms (86% market-relative), so this remains
the one open item that could still move the out-of-sample number — though it is a
smaller lever than the earlier "the premium lives in the short leg" framing implied.

**Retracted, not adjusted:** an earlier version reported that the paper-faithful
spread's estimated market beta was ~0.005, "independently reproducing the paper's CMKT
beta of ~0.03". That is wrong. 0.005 was a zero-floored *hedge ratio* at a discarded
tuning setting, not a market beta. At the frozen parameters the clipped beta is exactly
zero in all 133 evaluation weeks, and the spread's true out-of-sample beta is strongly
**negative** (rolling mean −0.468, static OLS −0.535). **The spread is not
market-neutral out of sample.** Any claim of reproducing the paper's β_CMKT is
withdrawn.

**Carried verbatim (SPEC §10):** the source paper's headline 3.87%/week is a
frictionless upper bound; its abnormal return concentrates in a short leg that was
largely untradable over the sample; backtested returns do not predict live returns.
*(The middle clause is the paper's own characterisation, reproduced as written. Our
raw-return decomposition does not reproduce it: in our replication 97% of the in-sample
premium is long leg, and the short-leg concentration appears only market-relative.)*

---

## Bottom line

CTREND was real and is faithfully reproducible over its published window. Four years
on, what remains is a ~1%/week frictionless spread whose long leg — the side that
supplied 97% of the original premium and the side any investor can actually hold — has
lost 85% of its return and is no longer distinguishable from zero (t 1.14). The short
book is in better shape than we previously reported: a majority of it by dollar weight
is now shortable. It is not enough. Every implementable version is statistically
indistinguishable from noise (masked-short 0.68%/wk t 1.20; long-only 0.53%/wk t 1.00),
the spread is not market-neutral out of sample (β ≈ −0.5), and none of this yet charges
borrow cost, funding, market impact or capacity limits against ~70% weekly turnover.

Six pre-registered repairs, in nine configurations, did not rescue it: no configuration
clears its own pre-registered threshold, every q_BH is 0.973, zero Bonferroni tests pass,
and the SPA p-value is **0.726**.

*No live orders were placed or enabled at any point. This is evidence, not a trading
system, and is not investment advice.*
