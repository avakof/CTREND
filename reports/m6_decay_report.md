# M6 — Out-of-sample decay and implementability

Date: 2026-07-19 · Sample **201510 – 202629** (598 CTREND weeks) · split at **202222**,
the end of the paper's sample · 354 in-sample weeks vs **215 genuinely out-of-sample**.

Data: 20,673,212 daily CMC snapshot rows → 625,964 coin-weeks, 6,861 coins,
**5,071 delisted (73.9%)**. High/low coverage 94.8%, complete-case 92.2%.

---

## 1. Headline: the effect decayed by ~73%, and what survives is the untradable half

| | in-sample (≤202222) | out-of-sample (>202222) | change |
|---|---|---|---|
| **A — paper-faithful H−L** | **3.89%/wk** (t 4.17, SR 1.60) | **1.03%/wk** (t 2.27, SR 1.12) | **−73%** |
| B — feasibility-masked short | 2.85% (n=58) | **0.61%** (t 1.06, SR 0.53) | not significant |
| C — long-only, top-half liquidity | 3.69% (t 4.00) | **0.53%** (t 1.00, SR 0.49) | not significant |

**The frictionless spread remains statistically significant out of sample (t = 2.27)
but at roughly a quarter of its historical magnitude. Every implementable variant
loses significance.**

## 2. The long leg is gone; the premium is now entirely short-side

| leg | in-sample | out-of-sample |
|---|---|---|
| long (q5 − market) | **1.85%/wk** | **0.15%/wk** |
| short (market − q1) | **2.04%/wk** | **0.88%/wk** |

In sample the premium was roughly balanced. Out of sample the long leg has
**essentially vanished** (0.15%/week, economically indistinguishable from zero) and
**85% of what remains comes from shorting the bottom quintile**.

That matters because the short leg is precisely the part that cannot be traded.

## 3. The short leg was, and largely remains, unshortable

Binance USDT-M perpetual `onboardDate` is an exact record of when a coin first became
shortable on the dominant venue. Of 6,861 panel coins, **817 (11.9%) ever had a
perpetual**, and the first contract (BTC) only onboarded in **September 2019**.

| | share of bottom-quintile names with a live perpetual |
|---|---|
| in-sample (2015–2022) | **1.0%** |
| out-of-sample (2022–2026) | **14.7%** |

For essentially the whole of the paper's sample the short book was un-implementable —
99% of the names it wanted to short had no perpetual venue. Shortability has improved
materially since, but even now roughly six in seven short-leg names cannot be shorted
this way.

This is the concrete content of the paper's own disclosure (SPEC §10) that the
abnormal return "concentrates in a short leg that was largely untradable over the
sample". M6 converts that caveat into a measurement: **restricting the short book to
what could actually be shorted cuts the out-of-sample spread from 1.03% to 0.61%/week
and removes its statistical significance (t = 1.06).**

Caveat, stated plainly: perpetuals are a **lower bound** on shortability. Margin
borrow and OTC routes existed for some names, and historical borrow availability is
not publicly reconstructible, whereas perp onboarding is exact. Variant C (long-only)
brackets the same question from the opposite side and reaches the same conclusion —
0.53%/week, t = 1.00 — so the finding does not rest on the mask alone.

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
