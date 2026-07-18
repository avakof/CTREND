# M1 Data Inventory — CP-1 Report

Date: 2026-07-18. Status: **CP-1 STOP — awaiting user decisions.**
Nothing purchased, no credentials used, no data redistributed.

---

## 1. Track A inventory (Harvard Dataverse, doi:10.7910/DVN/NTIVT8)

Downloaded and extracted: **68 files, 0.5 MB, CC0**, to `data/raw/dataverse_NTIVT8/`.

| Content | Count | Note |
|---|---|---|
| MATLAB source (`.m`) | 66 | driver scripts `b00`–`b18` + `Utils/` |
| `Results/CTREND/CTREND.xlsx` | 1 | **the authors' actual factor series** |
| `0_readme.txt` | 1 | execution order + external data list |

### 1.1 FINDING: the package contains NO panel data

`b01ReadData.m` expects six CSVs in `./DATA/` that **are not shipped**:
`close_cmc.csv`, `low_cmc.csv`, `high_cmc.csv`, `open_cmc.csv`,
`market_cap_cmc.csv`, `volume_cmc.csv`, plus `MetaData.mat`.

The suffix `_cmc` and readme line 21 ("reads the CoinmarketCap data") confirm the
source was CoinMarketCap, which the authors could not redistribute. What ships
instead is `b01GenerateArtificialData.m` — pure Gaussian noise (`randn`), which
readme line 19 calls "only useful for technical check". It has no cross-sectional
signal structure and cannot validate anything about CTREND's economics.

**Consequence: the M1 definition-of-done in SPEC §6 — "yearly coin counts and
mean/median market cap and volume within ±2% of the paper's Table 1" — is
UNACHIEVABLE from Track A.** Table 1 cannot be reproduced without the panel.

### 1.2 WIN: the shipped factor series is a direct validation target

`Results/CTREND/CTREND.xlsx`, sheet `Data from Study`: 371 weekly observations,
`YYYYWW` 201516 → 202222. Verified independently:

| Statistic | Shipped series | Paper | Match |
|---|---|---|---|
| Mean %/week | **3.866** | 3.87 | ✓ |
| Annualized Sharpe | **1.944** | 1.94 | ✓ |
| SD %/week | 14.342 | — | — |
| Fraction positive | 0.593 | — | — |

This is the paper's headline H−L series. It permits **week-by-week correlation
validation** of a reconstruction — strictly stronger evidence than landing inside
the SPEC §7 bands. Recommend adding it as a primary gate.

Date convention (from the readme sheet): *"we follow the convention in Liu,
Tsyvinski, and Wu (2022, JF) and divide the year into 52 weeks. The date format
is YYYYWW."*

---

## 2. Ground truth extracted from the authors' MATLAB code

The shipped code is the authoritative record of what produced the published
numbers. Reading it against SPEC.md found divergences well beyond ambiguities
A1–A5. Ordered by impact. **These are corrections of our reading of the paper,
identified before any result was computed — not post-hoc tuning (I3).**

| # | SPEC.md says | Authors' code does | File evidence | Impact |
|---|---|---|---|---|
| 1 | Weeks end Sunday (A3) | **No weekday.** Year sliced into fixed 7-day blocks from Jan 1; 52 wk/yr; wk 52 is 8–9 days; boundaries drift each year | `fResampleLiuEtAl.m:53-89`; `b02:16` `lResampleLiuEtAl=true` | changes every obs |
| 2 | α,β = per-week trailing means over M=52 | **One** (ᾱ,β̄) pair — mean of 52 weekly WLS gammas — applied to all training weeks and OOS | `fEstFamaMacBethPanel.m:156-157`; `fPredictFamaMacBethPanel.m:67` | §4.3 steps 2–3 wrong |
| 3 | Truncate weekly, full-sample percentiles (A5) | **Daily, per-day cross-sectional**; sets to NaN (drops), cascades to close/mcap/vol/OHLC | `b02:66-81`; `fTruncate.m:21-30`; `fEnsureAllObs` | changes universe |
| 4 | Lambda grid `logspace(-4,0,25)` | **200 data-dependent** lambdas, `lambda_max` → `1e-4·lambda_max` | `fEstRegPanelRegression.m:50,82-94` | see §2.1 |
| 5 | macd ÷ **fast** EMA (A1) | ÷ **slow** EMA — calls the PPO function | `b02:199`; `technical_indicators.m:474,510` | A1 resolved |
| 6 | Demean returns **and** forecasts | Only **returns**, equal-weighted; forecasts get a global intercept, no time FE | `b05:133-137`; `fEstRegPanelRegression.m:85` | §4.3 step 4 |
| 7 | Newey–West HAC t-stats | Plain **OLS/iid**; paper's t=4.22 is an OLS t | `b06:190,202,207`; `b14:158` | t-stats won't match |
| 8 | Excess returns minus rf | **No risk-free anywhere** — `vRiskFree` written, never read. Plus a **stablecoin exclusion** SPEC omits | `b01ReadData.m:134,175`; `b05:62-74` | set `risk_free: 0` |
| 9 | Chaikin 20d (A2) | **21d, min 10 obs** | `b02:221` | A2 resolved |
| 10 | SMAs NaN until warm-up | **Expanding window** w/ omitnan — `sma_200d` non-NaN from day 1 | `technical_indicators.m:100-107` | naive port loses ~6 mo/coin |
| 11 | AICc k = nonzero + 1 | k = nonzero, **no +1** (penalty otherwise algebraically identical) | `fEstRegPanelRegression.m:108` | minor |
| 12 | stoch* bounded [0,100] | **[0,1]** — SPEC's property test would fail a faithful port | `technical_indicators.m:609-616` | fix test |

Confirmed correct in SPEC: the 28-indicator list (exact match), market-cap WLS
weights (lagged, normalized), θ_j > 0 strict selection, equal-weighting of
survivors, [−0.5,+0.5] rank map, GKX turnover (half sum |Δw|, averaged across
legs), the 30/40–50/60 bps cost schemes, Lo (2002) Sharpe test, and the LTW
factor reconstruction (CSMB 30/70 size ×(−1), CMOM 3-week momentum).
No cross-validation appears anywhere — I2 is consistent with the code.

### 2.1 Correction to the lambda-grid severity assessment

The initial extraction rated item 4 as critical, claiming SPEC's fixed grid sits
entirely above `lambda_max` so **nothing would be selected** and CTREND would be
degenerate. **Tested and NOT supported.** Across signal strengths (corr
0.002–0.04) and panel sizes (n = 3,120 and 15,600), `lambda_max` lands at
0.006–0.014, leaving **11–13 of the 25 grid points usable in every regime**.

The real, narrower finding: the fixed and data-dependent grids selected
**different indicator sets in 5 of 10 tested cases**. Not fatal, but not
equivalent. Adopting the authors' data-dependent grid is correct for fidelity
and is scale-invariant — but it is not a survival issue.

### 2.2 A genuine look-ahead bug in the authors' own resampler

`fResampleLiuEtAl.m:109-121` — when a coin has ≥1 observation in a week but the
week's final day is missing, the fallback searches `mDataTemp` (the **year**
slice) instead of `mDataDailyTemp` (the **week** slice), substituting the last
non-missing value in the entire calendar year — a **future** value for any week
before December. The correct week-local logic exists in `fResampleDay2Week.m:102`.

Blast radius: everything resampled with `'last'` — all 28 indicators, close,
market cap. Returns (`'prod'`) and volume (`'sum'`) unaffected. Worst for
illiquid, gappy coins and coins that die mid-year.

**This creates a direct conflict with invariant I1: a faithful port will FAIL
`tests/test_no_lookahead.py` by construction.** Recommend implementing the
corrected version as default with `liu_resample_lastfix: {faithful, corrected}`
to quantify the gap against the shipped factor series.

---

## 3. Data source options (all verified live this session)

### 3.1 Free sources — VERIFIED WORKING

**(a) CoinMarketCap internal snapshot API — no key, no cost**
```
https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical
    ?date=YYYY-MM-DD&start=1&limit=10000&convert=USD
```
Independently verified: HTTP 200, no credentials. Returns `price`, `marketCap`,
`volume24h`, `circulatingSupply`, `cmcRank`, `dateAdded`. BTC = $16,477.59 on
2018-01-07 (matches known history). **BitConnect present at rank 26 with $2.33B
market cap** — i.e. dead coins are structurally retained. Coverage 545 coins
(2015-04) → 9,704 (2022-05). **No high/low fields.**

Same endpoint wrapped by the CRAN package `crypto2` (v2.0.5, MIT) and used by
Ammann/Burdorf/Liebi/Stöckl, *Survivorship and Delisting Bias in Cryptocurrency
Markets*, which measures 62.19% annualized survivorship bias — direct support for
the concern in SPEC §10 about the short leg.

⚠️ **Undocumented internal endpoint.** No stability guarantee; CMC ToS prohibit
redistribution and derivative index creation. A full daily harvest is ~2,600
requests / ~8.9M rows. **Requires user authorization before harvesting (CP-2).**

**(b) Gandal/Hamrick/Moore/Vasek — Harvard Dataverse, CC0 — DOWNLOADED & VERIFIED**
`doi:10.7910/DVN/JPEF8T` → `data/raw/gandal_coin_data.csv` (66 MB).

| Check | Verified result |
|---|---|
| Rows / coins | 662,919 / **1,082** |
| Date range | 2013-04-28 → **2018-02-06** |
| Fields | `open, high, low, close, volume, market_cap` — **full OHLC** |
| Dead coins | **161** last observed >30d before end |
| After mcap ≥ $1M and ≤ BTC | 616 coins, 116,844 rows, **150 weeks** |
| Weekly cross-section | **median 69** (min 24, max 499) |
| Field completeness after filters | **100%** |

Identifier column is `market` (not `tag`, which is a category label);
`market_cap`/`volume` are comma-quoted strings needing parse.

Median 69 coins/week clears the authors' own thresholds (`iMinNumCS=25`,
`iMinNumAssets=5`), giving ~14 coins per quintile. **A genuine replication is
runnable on free CC0 data today** over Apr 2015 – Feb 2018 = **40% of the paper
window**. Companion token file `doi:10.7910/DVN/H98LCZ` adds 1,905 tokens to
2019-10 (different schema and date format — needs harmonizing).

**(c) LTW three-factor series — VERIFIED DOWNLOADABLE**
`https://www.dropbox.com/s/ziyh9pjooroxali/LTW_3factor.xlsx?dl=1` (via
yukunliu.com/research). 479 weekly obs `yyww` 201404→202314, columns
`cmkt|csize|cmom`, **373 obs inside the Apr 2015–May 2022 window**, zero missing.
Satisfies the SPEC §4.4 factor cross-check (≥0.95 correlation gate).
Their note: "data are from coingecko since mid-2020." Factors only — no panel.

**(d) Zenodo 4946058 (CC0)** — 2,475 coins 2013-04→2018-02 with an explicit
`inactive` flag (**977 of 2,475 = 39.5% inactive**) — the cleanest survivorship
labeling found. Market cap + close only; **no volume, no H/L**. Cross-validation use.

### 3.2 Free sources — RULED OUT (verified)

| Source | Why |
|---|---|
| CoinGecko public API | **365-day cap** (error 10012). Unusable for the window |
| CoinMetrics community | mcap for only **320 assets, 12 reaching Apr 2015**. Too narrow for quintiles |
| Binance / ccxt | **No market cap at all**; starts 2017-08. Useful for Track B prices + the A4 feasibility mask (`exchangeInfo` retains 2,283 delisted symbols) |
| Babiak & Bianchi (JFQA) | 100 **anonymized** tickers, zero attrition — fully survivor-biased |
| Zenodo / figshare / Dryad (other) | Top-N, survivor-only, or aggregate-level |

### 3.3 Paid options (for reference — NOT purchased)

| Option | Cost | Note |
|---|---|---|
| CMC official API **Startup** | **$79/mo** | Licensed. Deep history is **not** enterprise-only — corrects a prior assumption |
| CoinGecko Analyst | $129/mo | No dead-coin guarantee — weaker than CMC for more money |
| CoinDesk Data (ex-CryptoCompare) | key required | Explicitly retains delisted instruments (`RETIRED` = "retained for historical purposes"); 10k+ coins to 2010. Could not empirically confirm — all data endpoints need a key |
| Coin Metrics academic program | $0 | Apply regardless; coverage ceiling (12 assets to 2015) is fatal alone |
| Kaiko | ~$1–2.5k/mo | **Disqualified** — market cap only from Sept 2025 |
| Amberdata | ~$45k/yr | **Disqualified** — mcap top-230 only |

### 3.4 The residual gap: high/low

Needed by 4 of 28 indicators (`stochK`, `stochD`, `cci`, `chaikin`). The CMC
snapshot endpoint has no H/L, and CMC's per-coin OHLC endpoint is
survivorship-biased **exactly where the alpha lives**: in the 2018-01 smallest
quintile only ~35% of coins have H/L vs ~90% in the largest; long-dead coins ~8%.
Free CC0 sources with H/L (Gandal 2013–2018/2019) cover the early window well.
Any residual needs a documented handling rule in DECISIONS.md.

---

## 4. Recommendation

**Phase 1 — free, zero spend, no ToS exposure.** Build on the Gandal CC0 panel
(Apr 2015 – Feb 2018, 150 weeks, median 69 coins/week, full OHLC, dead coins
retained). Validate the reconstruction **week-by-week against the shipped
`CTREND.xlsx`**, whose 371 weeks fully cover this span. After the 52-week
burn-in this leaves ~98 evaluable weeks.

This proves the implementation is correct **before** any purchase decision, and
inverts the risky ordering of buying data first.

Honest limits: ~98 weeks vs the paper's 371 → materially less power (a true
3.87%/wk effect gives t ≈ 2.7, not 5.2). The span covers the 2017 bubble and
ends before the 2018 crash, so **the SPEC §7 bands — calibrated on the full
sample — are NOT the right gate for it.** Correlation against the shipped factor
is the sounder test.

**Phase 2 — requires authorization (CP-2).** Close Feb 2018 → May 2022 either by
harvesting the CMC internal API (free, ToS caveat) or the licensed CMC Startup
tier ($79/mo). Only worth doing once Phase 1 validates.

---

## 5. Open decisions for the user

1. **Data.** Approve Phase 1 (free CC0, no authorization needed)? And for
   Phase 2 — harvest the undocumented CMC endpoint, or pay $79/mo for licensed
   access?
2. **Fidelity.** Rewrite SPEC.md to match the authors' code (flagged in
   DECISIONS.md per I2), or hold SPEC as-is and log divergences?
3. **The authors' bug.** Faithful port (fails I1) or corrected (won't match their
   numbers)? Recommend both behind `liu_resample_lastfix`.
4. **Gates.** Given a 2015–2018 sub-period, replace the SPEC §7 bands with
   correlation against the shipped factor as the primary M5 gate?
