# CTREND — Executive Summary

Replication and out-of-sample extension of Fieberg, Liedtke, Poddig, Walker &
Zaremba, *A Trend Factor for the Cross Section of Cryptocurrency Returns*,
JFQA 60 (2025), 3116–3153.

2026-07-19 · 137 tests green · full detail in `validation_report.md` and
`reports/m6_decay_report.md`.

---

## The replication succeeds. The strategy does not survive out of sample at an implementable magnitude.

**We reproduced the paper.** Over its own window (Apr 2015 – May 2022) all **seven**
immutable acceptance bands pass: H−L **3.945%/week** (paper 3.87), Sharpe **1.620**
(1.94), CMOM beta **0.771** (0.79), alpha vs LTW **2.94%** with t **3.42**, turnover
**70.1%** (68.45). Against the authors' own published factor series our reconstruction
correlates at **Spearman 0.818** with **84.1%** weekly sign agreement, and the means
differ by **0.04 pp**. Net-of-cost returns land on the paper's Table 9 almost exactly
(2.95 / 2.67 / 2.39 vs 2.90 / 2.62 / 2.35), and breakeven transaction cost matches at
**1.41%**. None of this was calibrated; the bands were fixed before any result was
computed.

**Extended to today (215 genuinely out-of-sample weeks, to July 2026), it decays by
73%** — from 3.89%/week to **1.03%/week**. The frictionless spread stays statistically
significant (t = 2.27) but at roughly a quarter of its historical size.

**Every implementable version loses significance:**

| | in-sample | out-of-sample |
|---|---|---|
| paper-faithful H−L | 3.89%/wk (t 4.17) | **1.03%/wk** (t 2.27) |
| short book restricted to what could be shorted | — | **0.61%/wk** (t 1.06) |
| long-only, top-half liquidity | 3.69%/wk (t 4.00) | **0.53%/wk** (t 1.00) |

**Why: the tradable half of the premium is the half that disappeared.** In sample the
long and short legs contributed roughly equally (1.85% and 2.04%/week). Out of sample
the long leg is **0.15%/week — economically zero** — and 85% of what remains comes
from shorting the bottom quintile.

That is the half that cannot be traded. Using Binance perpetual onboarding dates as an
exact record of shortability: only **11.9%** of the 6,861 coins in our panel ever had a
perpetual, the first contract onboarded in **September 2019**, and of the names the
strategy wants to short, **1.0% were shortable in-sample and 14.7% today**.

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
independently.

**Solid but caveated:** the out-of-sample decay. It rests on a panel rebuilt from CMC
daily snapshots, since the authors' replication package ships **MATLAB code only, no
data**. Our universe runs ~16% larger than theirs from 2018 onward because CMC has
backfilled its history since 2022 — a documented failure of the M1 sample gate
(14/40 cells) that we deliberately did **not** tune away.

**The main residual limitation:** high/low data is missing for ~5% of coin-weeks,
concentrated in delisted coins, which biases the short leg. Since the short leg is
where the surviving premium lives, this is the one open item that could still move the
out-of-sample number.

**Carried verbatim (SPEC §10):** the source paper's headline 3.87%/week is a
frictionless upper bound; its abnormal return concentrates in a short leg that was
largely untradable over the sample; backtested returns do not predict live returns.

---

## Bottom line

CTREND was real and is faithfully reproducible over its published window. Four years
on, what remains is a ~1%/week frictionless spread whose tradable long side has gone
to zero, whose surviving edge sits in a short book that is mostly unshortable, and
which is statistically indistinguishable from noise once implementation constraints
are applied — before any borrow cost, funding, market impact or capacity limit is
considered, and against ~70% weekly turnover.

*No live orders were placed or enabled at any point. This is evidence, not a trading
system, and is not investment advice.*
