# M6 — Out-of-sample decay and implementability

Date: 2026-07-19 · **corrected 2026-07-21** · Sample **201510 – 202629**, i.e.
**569 weeks with a valid cross-section** out of 592 calendar weeks · split at
**202222**, the end of the paper's sample · **354 in-sample** weeks (of 377 calendar
weeks; the 23 missing weeks all fall in 2015–16 and lack a valid cross-section) vs
**215 genuinely out-of-sample** (of 215). The in-sample block opens at Liu week
201510 = 2015-03-05..03-11 and closes at 202222, which ends **2022-06-03**; the final
out-of-sample week 202629 is a 3-day stub (the daily panel ends 2026-07-18 inside a
block spanning Jul 16–22).

Data: **20.67M raw CMC daily snapshot rows** (20,673,212 rows across 34,107 coin ids)
→ curated daily panel 19,526,231 rows / 31,856 coins → **626k coin-weeks
(625,964) across 6,861 coins**, of which **5,071 delisted (73.9%)**. Restricted to
those 6,861 panel coins the daily panel is 8,648,498 coin-days. High/low coverage
94.8%, complete-case 92.2%.

---

> ### Correction (2026-07-21)
>
> An adversarial audit confirmed four errors in the 2026-07-19 version of this report.
> All are corrected below; nothing is quietly deleted.
>
> 1. **§2 leg decomposition — the material error.** The table labelled its rows
>    "long" and "short" and the text read them as raw returns, but both columns were
>    **market-relative** (q5 − mkt and mkt − q1). The claim that **"85% of what
>    remains comes from shorting the bottom quintile"** — and the companion claim that
>    in sample the legs "contributed roughly equally" — are **retracted**. On raw
>    returns the long leg supplied **97%** of the in-sample premium and then collapsed
>    by 85% out of sample (+3.794 → +0.585 %/wk). The market-relative split is not
>    wrong, but it is a beta-adjusted quantity and must never be used to argue about
>    tradability. §2 now reports both, labelled.
> 2. **§1/§3 variant B.** Regenerated after three never-traded `PENDING_TRADING`
>    contracts were dropped and the onboard/offboard **interval** predicate replaced a
>    half-line: in-sample 2.85% (n=58) → **2.919% (n=56, t 1.50)**, out-of-sample
>    0.61% (t 1.06) → **0.684% (t 1.20)**. Still not significant.
> 3. **§3 shortability was understated.** The old table gave **headcount** share only.
>    Every return here is value-weighted, so the **market-cap-weight** share is the one
>    that bears on tradability, and it is far higher: **53.1%** of the out-of-sample
>    short book by weight was shortable, 62.0% over the last 52 weeks. The sentence
>    "roughly six in seven short-leg names cannot be shorted" is **retracted** as a
>    statement about the short *book*; it is true only of names, not of dollars.
> 4. **§3 mask bias.** The "lower bound" framing here was and remains correct (the
>    README and `reports/upgrades_evaluation.md` asserted the opposite in their
>    2026-07-19 versions; both were corrected on 2026-07-21 to match this report), but it
>    was incomplete: the mask joins on a **bare ticker match**, which biases in the other
>    direction. Quantified below. The mask is not exact.
>
> Everything else — the decay itself, the year-by-year record, the loss of significance
> in every implementable variant — is unchanged and, on the long leg, worse.

---

## 1. Headline: the effect decayed by ~73%, and the half that collapsed is the tradable one

| | in-sample (≤202222) | out-of-sample (>202222) | change |
|---|---|---|---|
| **A — paper-faithful H−L** | **3.89%/wk** (t 4.17, SR 1.60) | **1.03%/wk** (t 2.27, SR 1.12) | **−73%** |
| B — feasibility-masked short | 2.92% (n=56, t 1.50) | **0.68%** (t 1.20, SR 0.60) | not significant |
| C — long-only, top-half liquidity | 3.69% (t 4.00) | **0.53%** (t 1.00, SR 0.49) | not significant |

**The frictionless spread remains statistically significant out of sample (t = 2.27)
but at roughly a quarter of its historical magnitude. Every implementable variant
loses significance.**

## 2. The long leg carried the premium, and the long leg is what collapsed

> **Retraction (2026-07-21).** The previous version of this section reported only the
> two **market-relative** columns while describing them as the long and short legs of
> the trade, and concluded that in sample the legs "contributed roughly equally" and
> that out of sample **"85% of what remains comes from shorting the bottom quintile"**.
> Both conclusions are withdrawn. They are artefacts of subtracting the market return
> from the long leg and adding it to the short leg, which mechanically transfers a
> +1.94%/wk in-sample market return from one side of the ledger to the other. The
> "surviving premium sits in the short leg" thesis **does not hold in raw terms.**

`reports/m6_variants.csv` now carries four leg columns, not two. Both decompositions
sum to the same H−L; they differ in where the market return is booked.

| decomposition | leg | in-sample | out-of-sample |
|---|---|---|---|
| **raw** (the return the leg actually earned) | long = q5 | **+3.794%/wk** (t 3.66, **97%**) | **+0.585%/wk** (t 1.14, 57%) |
| | short = −q1 | +0.101%/wk (t 0.14, 3%) | +0.445%/wk (t 0.63, 43%) |
| | *memo:* market | +1.939%/wk | +0.438%/wk |
| **market-relative** (beta-adjusted; **not** a tradable return) | long = q5 − mkt | +1.855%/wk (48%) | +0.148%/wk (14%) |
| | short = mkt − q1 | +2.039%/wk (52%) | +0.882%/wk (86%) |

Read on **raw returns**, which is what a book actually earns:

* In sample the trade was **almost entirely a long bet**: the top quintile returned
  +3.794%/week and the short leg contributed +0.101%/week — 3% of a 3.894% spread, with
  a t of 0.14. The bottom quintile was very nearly flat, not sharply negative.
* Out of sample the long leg fell from +3.794% to **+0.585%/week, an 85% collapse**,
  and is no longer distinguishable from zero (t 1.14). The short leg rose slightly, to
  +0.445%/week, and is also indistinguishable from zero (t 0.63).
* Neither raw leg is individually significant out of sample. The spread's t = 2.27
  comes from the *difference*, which is far less volatile than either side.

Read on **market-relative returns** the picture inverts — 86% of the surviving spread
sits in the short leg — because out of sample the market itself returned only
+0.438%/week, so almost all of q5's raw return is absorbed as market exposure. That
number is a correct description of the beta-adjusted decomposition and a misleading
one about tradability. It is quoted here only so the two can be told apart.

The damning version is therefore the opposite of what this report previously said:
**the side that generated the historical premium is the long side — the side that is
trivially implementable — and it is the side that vanished.**

## 3. The short leg was unshortable in sample; out of sample most of it, by weight, is not

Binance USDT-M perpetual `onboardDate` records when a coin first became shortable on
the dominant venue. Of 6,861 panel coins, **814 (11.9%) ever had a perpetual that
traded** (817 matched to a perpetual, less three whose only contract is
`PENDING_TRADING` and has never traded), and
the first (BTC) only onboarded in **week 201936, September 2019**. The share of the
short book with a live perpetual is **exactly zero for 4.71 years**, from 2015-03-11 to
2019-11-25.

Two shares matter, and the previous version of this report gave only the first. Every
return in this report is **value-weighted**, so the market-cap-weight share is the one
that bears on whether the short book could be put on:

| | headcount share | **market-cap-weight share** |
|---|---|---|
| in-sample / paper window (2015–2022) | 0.94% | **11.37%** |
| out-of-sample (2022–2026) | 14.69% | **53.09%** |
| last 52 weeks | 26.34% | **62.01%** |

> **Correction (2026-07-21).** The headcount figures moved slightly (0.95 → 0.94,
> 14.75 → 14.69) because the three never-traded contracts are now excluded and the
> mask applies the onboard/offboard **interval** predicate rather than a half-line.
> The substantive change is the second column, which was absent: the earlier statement
> that "roughly six in seven short-leg names cannot be shorted this way" is **retracted
> as a claim about the short book**. It remains true of *names*. It is false of
> *dollars*: **out of sample the majority of the short book by weight — 53.1%, and
> 62.0% over the last 52 weeks — was shortable**, and in 126 of the 215 out-of-sample
> weeks more than half the short book's weight had a live perpetual. The short side is
> substantially more implementable than this report previously conceded.

For essentially the whole of the paper's sample the short book was still
un-implementable: 99% of the names, and 89% of the weight, had no perpetual venue.
That is the concrete content of the paper's own disclosure (SPEC §10) that the abnormal
return "concentrates in a short leg that was largely untradable over the sample", and
M6 converts the caveat into a measurement: **restricting the short book to what could
actually be shorted cuts the out-of-sample spread from 1.03% to 0.684%/week and removes
its statistical significance (t = 1.20).** Note that this is now a statement about
cost and capacity, not about impossibility — post-2022 the constraint bites on the
long tail of small names, not on the bulk of the book.

Caveat, stated plainly, and in **both** directions — the mask is bounded on each side
and it is **not exact**:

* **Biases the measured shortable set DOWN.** Perpetuals are a **lower bound** on
  shortability: margin borrow and OTC routes existed for some names, and historical
  borrow availability is not publicly reconstructible whereas perp onboarding is
  dated. Separately, `exchangeInfo` returns only contracts that exist today, so a coin
  that had a perp and was later *fully* delisted is absent and reads as never-shortable.
  Both mechanisms shrink the shortable set. (The 2026-07-19 README and
  `reports/upgrades_evaluation.md` described the `exchangeInfo` survivorship channel as
  making the mask an *upper* bound. That was backwards; the direction stated here and in
  `src/ctrend/costs/feasibility_mask.py` is the correct one, and both of those documents
  were corrected to match on 2026-07-21.)
* **Biases it UP.** Shortability is assigned by a bare **ticker** match
  (`feasibility_mask.py` joins `upper(perp.base) = panel.sym`). About 145 perp tickers
  are shared by ~342 panel coins, so up to ~197 coins are marked shortable purely by
  ticker collision. Deduplicating to the largest coin per ticker drops the
  out-of-sample headcount share from 14.7% to **13.6%** — a real but second-order
  effect relative to the survivorship and venue-coverage channels above.

Variant C (long-only) brackets the same question from the opposite side and reaches the
same conclusion — 0.53%/week, t = 1.00 — so the finding does not rest on the mask alone.

## 4. Year by year — the post-2022 record is unstable, not monotonically decaying

> **Correction (2026-07-19).** An earlier version of this section reported rolling
> 52-week Sharpe *labelled by year* and concluded "the collapse is concentrated in
> 2025". That was wrong. A rolling 52-week statistic is dated by its **end** week, so
> the value printed under 2025 summarised mid-2024 → mid-2025. Attributing it to
> calendar 2025 inverted the actual result: 2025 was a *strong* year and **2024** was
> the bad one. Calendar-year figures below replace it.

Frictionless H−L (variant A), by calendar year:

| year | weeks | mean %/wk | total % | Sharpe | max DD % |
|---|---|---|---|---|---|
| 2019 | 52 | 2.67 | +264.0 | 3.26 | −10.5 |
| 2020 | 52 | 3.32 | +291.4 | 1.93 | −24.8 |
| 2021 | 52 | 3.10 | +272.0 | 2.12 | −34.3 |
| 2022 | 52 | 0.88 | +44.1 | 1.05 | −28.7 |
| 2023 | 52 | 2.14 | +187.0 | 3.50 | −12.0 |
| **2024** | 52 | **−0.77** | **−41.9** | **−0.75** | **−59.8** |
| **2025** | 52 | **+2.29** | **+166.4** | **2.02** | −41.7 |
| 2026 | 29 | −0.33 | −14.2 | −0.38 | −15.7 |

The out-of-sample period is **not** a smooth decay. It is one very strong year (2023),
one severe loss year (2024, −41.9% with a 59.8% drawdown), one strong recovery (2025,
+166.4%), and a negative partial 2026. The 1.03%/week out-of-sample average is the
mean of highly dispersed annual outcomes, not a stable reduced edge.

This also weakens the "published-and-arbitraged-away" reading: the worst year (2024)
*precedes* the paper's 2025 publication, and 2025 itself was strong.

**The implementable variants tell a harsher and more consistent story.** In 2025, the
frictionless spread returned +166.4% while the long-only top-half-liquidity variant
returned **−13.0%**, and **−27.6%** after 50/60 bps costs. In 2026 to date: A −14.2%,
long-only **−35.2%**, net **−41.6%**. The tradable version lost money in both years,
including the year the headline strategy nearly tripled.

## 5. What did NOT change

Volatility fell sharply — 17.6% weekly in-sample to 6.7% out — so the Sharpe (1.12)
degrades far less than the mean (−73%). An investor sizing to a volatility target
would see a milder deterioration than the raw spread suggests. This is the one reading
under which the effect looks more durable, and it is why both mean and Sharpe are
reported side by side.

## 6. Reproduction

    make harvest        # ~90 min, hits CMC; see DECISIONS.md Part 3 on terms
    make all            # curate -> indicators -> CTREND -> canary -> gate
    make m6             # feasibility mask + variants

Artefacts: `reports/m6_variants.csv` (per-week series), `reports/m5_gate.csv`,
`data/curated/ctrend_weekly.parquet`.
