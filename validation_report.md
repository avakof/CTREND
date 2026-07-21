# CTREND — Validation Report (CP-3)

Replication of Fieberg, Liedtke, Poddig, Walker & Zaremba, *A Trend Factor for the
Cross Section of Cryptocurrency Returns*, JFQA 60 (2025), 3116–3153.

Date: 2026-07-19 · Sample **201516 – 202222, 353 weeks** · `configs/replication.yaml`
· 137 tests green.

---

## 1. Headline: the replication succeeds — 7 of 7 acceptance bands pass

| Metric (H−L) | Ours | Paper | Band | Verdict |
|---|---|---|---|---|
| Quintile means monotone Q1→Q5 | yes | monotone | strictly increasing | **PASS** |
| H−L mean, %/week | **3.945** | 3.87 | 3.0 – 4.7 | **PASS** |
| Annualised Sharpe | **1.620** | 1.94 | 1.5 – 2.4 | **PASS** |
| CMOM beta | **0.771** | 0.79 | 0.6 – 1.0 | **PASS** |
| Alpha vs LTW, %/week | **2.936** | 2.62 | > 0 | **PASS** |
| Alpha vs LTW, t-stat | **3.419** | 4.22 | > 3 | **PASS** |
| Weekly turnover, % | **70.085** | 68.45 | 55 – 80 | **PASS** |

Quintile means (%/week): **−0.10 → 1.20 → 1.49 → 2.33 → 3.85**.

### Independent confirmations not required by the gate

**Against the authors' own shipped factor** (`CTREND.xlsx`, 371 weeks, 353 overlapping):
Pearson **0.627**, Spearman **0.818**, weekly sign agreement **84.1%**. Their series
means 3.989%/week over the overlap; ours 3.945% — a gap of **0.04 pp**.

**Transaction costs vs the paper's Table 9** — not used to calibrate anything:

| scheme (long/short bps) | ours | paper |
|---|---|---|
| 30/40 | **2.95%/wk** (t = 3.15) | 2.90 (t = 3.89) |
| 40/50 | **2.67%/wk** (t = 2.85) | 2.62 (t = 3.53) |
| 50/60 | **2.39%/wk** (t = 2.55) | 2.35 (t = 3.16) |
| breakeven TC | **1.41%** | 1.41 |

**Table 2, all 28 indicators individually**: 23/23 correct signs among those the paper
finds \|t\| ≥ 1.0, median absolute difference 0.39 pp, correlation **0.968**.

**Pipeline canary** (run *before* CTREND was judged, per SPEC §6): 3-week momentum
H−L = **3.97%/week**, band 2.0–4.0, monotone quintiles. The sort/weight/turnover
machinery is validated independently of the novel signal.

---

## 2. Where we differ from the paper, and why

**Sharpe 1.62 vs 1.94.** The means agree to 0.04 pp; the entire gap is volatility —
17.6% weekly vs their 14.4%. This traces to a documented, deliberately un-tuned data
difference (§3 below): our universe runs ~16% larger from 2018 onward, adding small
volatile coins that raise the spread's variance without moving its mean.

**Alpha t 3.42 vs 4.22.** Same cause — higher residual variance. The alpha itself is
*larger* than the paper's (2.94% vs 2.62%). Under Newey–West the t is 4.07, but per
GT-12 the gate uses OLS, which is what the authors used.

**M1 sample gate FAILED and was not fixed.** Yearly coin counts and mean market cap
vs Table 1 pass 14/40 cells. 2015–2017 is near-exact (mean market cap within
0.1–1.6%); 2018+ diverges monotonically. Diagnosis: CMC has backfilled its historical
snapshots since the authors pulled data in 2022–23, so a 2026 harvest sees a larger
universe. This cannot be corrected from our side and **tuning the universe to close
the gap would be exactly the p-hacking I3 forbids**. Full analysis:
`reports/m1_table1_gate.md`.

**Factor reconstruction cross-check** (SPEC §4.4, gate ≥ 0.95): CMKT **0.954 PASS**;
CSMB 0.511 and CMOM 0.723 below gate. Expected — those factors depend on size and
momentum breakpoints within the universe, and our universe composition differs as
above. The paper's own baseline regresses on Liu's *published* factors (`b06:26`),
which is what the gate above uses; the reconstruction is the cross-check, and the
divergence is documented here as SPEC §4.4 permits.

---

## 3. What the replication corrected in the specification

Reading the authors' shipped MATLAB found **12 material divergences** from our reading
of the paper, all identified from primary source *before any result was computed*
(GT-1…GT-12, `DECISIONS.md`). The most consequential:

| # | Our original reading | The authors' actual code |
|---|---|---|
| GT-1 | weeks end Sunday | **no weekday exists** — fixed 7-day blocks from Jan 1, 52/yr, week 52 absorbs 8–9 days |
| GT-2 | truncate weekly, full-sample percentiles | **daily, per-day cross-sectional**, dropping the coin-day and cascading |
| GT-8 | α,β as per-week trailing means | **one (ᾱ,β̄) pair** per iteration, applied to all 52 training weeks |
| GT-9 | 25 fixed lambdas on [1e-4, 1] | **200 data-dependent**, `lambda_max` → `1e-4·lambda_max` |
| GT-4 | macd ÷ fast EMA | ÷ **slow** EMA — the paper's own footnote 3 agrees with the code against its body text |
| GT-12 | Newey–West t-stats | plain **OLS/iid**; the published t = 4.22 is an OLS t |

**GT-2 had a bonus effect**: because the authors' truncation is per-day, it contains
no look-ahead at all, so the A5 leakage channel is *closed*. The engine reports
`leakage channels declared open: none`, and the strict no-look-ahead test now runs in
the replication configuration rather than retreating to `expanding` mode.

We also found a **genuine look-ahead bug in the authors' own resampler**
(`fResampleLiuEtAl.m:109-121`): when a week's final day is missing, the fallback
back-fills from the last non-missing value in the whole *calendar year* — a future
value. Default is `corrected`, so invariant I1 holds; `faithful` is available to
quantify the difference.

---

## 4. Data provenance and its limits

Track A (Harvard Dataverse `doi:10.7910/DVN/NTIVT8`) ships **MATLAB code only, no
panel data** — the authors could not redistribute their CoinMarketCap source. The
panel was therefore rebuilt: **6,969,471 daily CMC snapshot rows** (2013-04-28 →
2022-05-31) curated to **273,384 coin-weeks across 3,787 coins, 2,359 delisted
(62.3%)**.

Dead coins are demonstrably present (BitConnect, Centra, TerraUSD), which matters:
the paper's abnormal return concentrates in the short leg of small failing coins, and
a survivor-only universe would inflate the result.

**High/low coverage is the main residual limitation.** Four indicators (`stochK`,
`stochD`, `cci`, `chaikin`) need daily highs and lows, and CMC has purged them for
~40% of delisted coin-weeks since 2022. Layering the CC0 Gandal panel
(`doi:10.7910/DVN/JPEF8T`, 1,601 verified coins) lifted delisted coverage from 59.3%
to **76.9%**; overall coverage is **89.8%**, complete-case **87.4%**. The two sources
were cross-validated on 186,876 overlapping coin-days: median \|log ratio\|
**0.00001** for both high and low.

The uncovered ~12.6% of coin-weeks is concentrated in delisted coins, so results here
carry a residual survivorship tilt in the *conservative* direction for the short leg.
This is the one open item that could still move the headline number.

---

## 5. Defects this build caught (all found by gates, not by inspection)

1. **Validator alignment.** First M3 validation returned Pearson −0.037; the
   validator scored each forecast one week late. Fixing it: −0.037 → 0.591.
2. **Duplicate coin-days.** A harvest crash-and-resume duplicated 4 dates (0.2% of
   rows); each doubled day failed `min_obs='all'` and voided the coin-week,
   collapsing 4 cross-sections from ~900 coins to ~18 — and because that leaves the
   smoothing window incomplete, **58 CTREND weeks were lost from 4 bad dates**.
3. **Zero prices.** CMC reports `0.0` for sub-denormal meme tokens; `close = 0` makes
   `sma_Xd = SMA/close` infinite, and since ranks are relative one infinity corrupts
   a whole week's cross-section.
4. **Silent API down-sampling.** CMC fits a ~732-point cap by *widening the interval*
   rather than erroring — multi-year OHLC requests returned 6-day bars that would
   have fed 14-day indicator windows without complaint.
5. **Factor dating.** The own-factor reconstruction was dated one week early;
   correlation with LTW went 0.063 → 0.954 on correction.

Each produced *plausible* output. None raised an error.

---

## 6. Standing disclosures (SPEC §10, carried verbatim)

The source paper's headline 3.87%/week is a frictionless upper bound; its abnormal
return concentrates in a short leg that was largely untradable over the sample;
backtested returns do not predict live returns.

To which this replication adds: the short leg is where our high/low coverage is
weakest, and net-of-cost returns fall to 2.39–2.95%/week before any borrow cost,
funding, market impact or shorting feasibility is considered. Turnover is ~70% per
week.

---

## 7. Status and next step

M0–M5 complete. **CP-3 reached — stopping for review.**

M6 (out-of-sample extension to the present, plus the implementable variants: 1-day
lag, long-only, liquidity screen, feasibility mask, perp-hedge) is the next milestone
and is where the question that actually matters — whether CTREND survived after
May 2022 and at what implementable magnitude — gets answered.
