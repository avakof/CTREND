# CTREND

Replication and out-of-sample extension of Fieberg, Liedtke, Poddig, Walker & Zaremba,
*A Trend Factor for the Cross Section of Cryptocurrency Returns*, **JFQA 60 (2025),
3116–3153**.

2026-07-19 · 177 tests green · Python 3.12, laptop scale (pandas + parquet + DuckDB)

> This is **evidence, not a trading system**. No live orders were placed or enabled at
> any point; the codebase contains no order-placement path. Not investment advice.

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
the long leg is **0.15%/week — economically zero** — and 85% of what remains comes from
shorting the bottom quintile.

That is the half that cannot be traded. Using Binance perpetual onboarding dates as an
exact record of shortability: only **11.9%** of the 6,861 coins in our panel ever had a
perpetual, the first contract onboarded in **September 2019**, and of the names the
strategy wants to short, **1.0% were shortable in-sample and 14.7% today**.

**Timing — unstable, not a smooth decline.** By calendar year the frictionless spread
returned +187% (2023), **−41.9% with a 59.8% drawdown (2024)**, **+166.4% (2025)**, and
−14.2% in 2026 to date. The 1.03%/week out-of-sample average is the mean of wildly
dispersed annual outcomes, not a stable reduced edge. Note the worst year *precedes* the
paper's 2025 publication, which weakens a simple "arbitraged-away" reading.

**The tradable version lost money even in the good year.** In 2025 the frictionless
spread returned +166.4% while long-only-within-liquid-names returned **−13.0%**, and
**−27.6%** net of 50/60 bps. In 2026 to date: −35.2% and −41.6% net.

**One reading is kinder.** Volatility fell from 17.6% to 6.7% weekly, so the Sharpe
(1.12) degrades far less than the mean. A volatility-targeting investor would see a
milder deterioration than the raw spread implies.

---

## Can it be repaired? A pre-registered test of six upgrades says no.

Six candidate upgrades were implemented, each with a **bit-exact identity default** so
the baseline could not move silently. Parameters were fitted on 2022–23, **frozen with
an integrity SHA**, and the ten configurations evaluated **once** on 2024–26 (133
weeks). Minimum detectable effects were written down before any result was read.

| config | mean %/wk | Sharpe | max DD | diff vs base | t |
|---|---|---|---|---|---|
| **C0 baseline** | 0.522 | 0.500 | −62.1 | — | — |
| C1 shortable universe + name cap | **−0.292** | −0.381 | −66.4 | **−0.860** | −1.95 |
| C2 vol targeting | 0.256 | 0.340 | **−49.2** | −0.266 | −1.22 |
| C3 turnover control | 0.530 | 0.548 | −55.6 | +0.008 | 0.04 |
| C4 beta hedge + funding | 0.522 | 0.500 | −62.1 | +0.000 | 0.74 |
| C5 selection stability | **0.611** | 0.594 | −52.2 | +0.089 | 0.46 |
| C6 capacity caps | 0.503 | **0.609** | **−48.3** | −0.019 | −0.03 |
| C7–C9 stacks | −0.30 … −0.85 | negative | −56 … −75 | −0.86 … −1.34 | — |

**Decisive null.** Every BH q-value is 0.973, zero Bonferroni passes, **SPA p = 0.643**,
and the Harvey–Liu–Zhu haircut zeroes the three positive differences at M = 10.

Two results carry information beyond the null:

* **C1, the highest-expected-value upgrade, is the worst.** Restricting to coins with a
  live perpetual gives −0.29%/wk against +0.52% baseline. Uncapped it makes +0.30%/wk
  with a top-1 weight of 0.629 and effective N of 3.45 — it *is* a BTC bet. Capping
  names at 10% (top-1 → 0.100, effective N → 31.6) flips the sign. It also failed in the
  tuning window, so this is not a regime artefact. **The edge lives in the names you
  cannot short.**
* **C4 is a well-powered no-op.** Mean beta of H−L on the market is 0.0048 — the spread
  is already market-neutral, independently reproducing the paper's own βCMKT ≈ 0.03. At
  an MDE of 0.04%/wk this is "nothing to hedge," not "we couldn't see it."

Where the design *did* help was risk, not return: C6 cut max drawdown 62.1% → 48.3% and
raised Sharpe to 0.609 on a slightly lower mean. That matches the pre-registered
expectation that 133 weeks resolves risk metrics far better than means.

Full detail, including per-configuration MDEs and the tuning-vs-evaluation transfer
table: [`reports/upgrades_evaluation.md`](reports/upgrades_evaluation.md).

---

## What to trust, and what not to

**Reliable:** the in-sample replication. It matches the authors' own factor week by week,
not merely on average, and reproduces their cost table and breakeven figure
independently.

**Solid but caveated:** the out-of-sample decay. It rests on a panel rebuilt from CMC
daily snapshots, since the authors' replication package ships **MATLAB code only, no
data**. Our universe runs ~16% larger than theirs from 2018 onward because CMC has
backfilled its history since 2022 — a documented failure of the M1 sample gate (14/40
cells) that we deliberately did **not** tune away.

**The main residual limitation:** high/low data is missing for ~5% of coin-weeks,
concentrated in delisted coins, which biases the short leg. Since the short leg is where
the surviving premium lives, this is the one open item that could still move the
out-of-sample number.

**Two biases in the upgrade experiment both cut toward optimism:** the perpetuals mask is
survivorship-biased (`exchangeInfo` returns only live contracts), so C1's universe is an
*upper* bound on shortability; and CMC volume is inflated by wash trading, so C6's
capacity constraint is looser than reality.

**Carried verbatim (SPEC §10):** the source paper's headline 3.87%/week is a frictionless
upper bound; its abnormal return concentrates in a short leg that was largely untradable
over the sample; backtested returns do not predict live returns.

---

## Bottom line

CTREND was real and is faithfully reproducible over its published window. Four years on,
what remains is a ~1%/week frictionless spread whose tradable long side has gone to zero,
whose surviving edge sits in a short book that is mostly unshortable, and which is
statistically indistinguishable from noise once implementation constraints are applied —
before any borrow cost, funding, market impact or capacity limit is considered, and
against ~70% weekly turnover. Six pre-registered attempts to repair it produce no
improvement that survives multiple-testing correction.

---

## Repository

### Documents

| file | what it is |
|---|---|
| [`SPEC.md`](SPEC.md) | Authoritative spec. §§4–8 verbatim from the paper, then reconciled against the authors' MATLAB with 12 ground-truth corrections marked `[GT-n]` and evidenced to `file:line`. Acceptance bands in §7 are immutable. |
| [`DECISIONS.md`](DECISIONS.md) | Ambiguity ledger. Every deviation, its justification, and the evidence behind it. |
| [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md) | The replication + decay findings above, standalone. |
| [`validation_report.md`](validation_report.md) | Full validation: gates, diagnostics, and the bugs found and fixed along the way. |
| [`UPGRADE_PLAN.md`](UPGRADE_PLAN.md) | Pre-registration for the upgrade experiment, written before results. |
| [`reports/`](reports/) | Per-milestone gates and outputs: `m1_table1_gate.md`, `m2_table2_gate.md`, `m3_validation.md`, `m6_decay_report.md`, `upgrades_evaluation.md`. |
| [`configs/frozen_params.json`](configs/frozen_params.json) | Frozen upgrade parameters with integrity SHA `6ee6c73db6dc…`. |

### Code

```
src/ctrend/
  calendar.py        Liu year-block weeks (GT-1): fixed 7-day blocks from Jan 1,
                     52 weeks/year, week 52 absorbs 8–9 days, phase resets annually
  data/              the Dataset.asof contract — the sole data-access path, which
                     is what makes invariant 1 testable rather than aspirational
  ingest/            CMC snapshots + OHLC, Gandal CC0 backfill, Binance funding,
                     daily → weekly curation
  indicators/        the 28 technical indicators, cross-sectional rank mapping
  signal/            CS-C-ENet: 28 univariate WLS regressions → smoothed (α,β) →
                     forecasts → ElasticNet with AICc λ selection
  portfolio/         value-weighted quintile sorts, GKX turnover, overlays
  costs/             transaction costs, Binance perpetual feasibility mask
  evaluation/        acceptance gates, factor regressions, KPIs
  experiments/       pre-registered harness: windows, freeze, BH/Bonferroni/HLZ/SPA
```

### Running it

```bash
make setup        # uv venv --python 3.12 && uv pip install -e .
make ingest       # build the panel     (needs data — see below)
make indicators   # 28 indicators, rank-mapped
make signal       # CS-C-ENet forecasts
make backtest     # quintile sorts, turnover, costs
make validate     # acceptance gates
make test         # 177 tests
```

**Data is not in this repo.** `data/` and `*.parquet` are gitignored — the curated panel
is ~2 GB and the CMC snapshot history is not ours to redistribute. `make ingest`
rebuilds it from source; see [`DECISIONS.md`](DECISIONS.md) Part 3 for exactly which
sources were used and how identity was resolved across them. The Gandal et al. daily
history is CC0 via Harvard Dataverse (`doi:10.7910/DVN/JPEF8T`,
`doi:10.7910/DVN/H98LCZ`).

Credentials, if any, come only from an untracked `.env` — see
[`.env.example`](.env.example). Public endpoints need none.

### Invariants

Enforced by tests, not convention:

1. **No look-ahead.** Week-*t* quantities use data ≤ *t*; all access goes through
   `Dataset.asof(week)`. `tests/test_no_lookahead.py` must stay green.
2. **No silent spec deviations.** A config flag *and* a `DECISIONS.md` entry are
   required. AICc λ selection is never replaced by cross-validation.
3. **Acceptance bands are immutable.** A failed gate means stop and diagnose — never
   parameter search until green.
4. Every module ships pytest tests.
5. Laptop scale only: pandas/polars + parquet + DuckDB. No services, no Spark.
6. Secrets only via untracked `.env`.
7. **Never emit live orders.** Order sheets (CSV) only.

---

*Source paper © the authors; this repository contains an independent reimplementation and
analysis, not their code or data.*
