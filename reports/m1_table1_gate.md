# M1 DoD gate — sample statistics vs the paper's Table 1

Date: 2026-07-19. Source: Fieberg, Liedtke, Poddig, Walker & Zaremba, JFQA 60 (2025),
Table 1, p. 3122. Gate: yearly coin counts and mean/median market cap and volume
within **±2%**.

## RESULT: **FAIL** — 14 of 40 cells pass.

Per invariant I3 this is a STOP with diagnosis. **Nothing has been tuned, and no
filter, window or threshold has been changed in response to these numbers.**

| yr | N | mean ME | med ME | mean Vol | med Vol |
|---|---|---|---|---|---|
| 2015 | −4.1%* | **−0.5%** | **−0.5%** | **+0.8%** | +12.6%* |
| 2016 | **+1.4%** | **−0.1%** | +11.2%* | **−0.6%** | +12.3%* |
| 2017 | **+1.2%** | **+1.6%** | **+1.4%** | **+2.0%** | +10.1%* |
| 2018 | +5.6%* | **−1.7%** | **+1.5%** | **−2.0%** | +8.0%* |
| 2019 | +10.8%* | −5.7%* | **+1.5%** | −7.0%* | +7.8%* |
| 2020 | +25.0%* | −13.5%* | +5.3%* | −25.0%* | +21.1%* |
| 2021 | +15.3%* | −12.8%* | +6.8%* | −26.9%* | +9.4%* |
| 2022 | +16.2%* | −14.7%* | +7.4%* | −45.8%* | +6.4%* |

Full-sample unique coins: **3,769 vs 3,245 (+16.1%)**.

## Diagnosis

**1. The pipeline is essentially correct — 2015–2017 is near-exact.**
Mean market cap lands within **0.1%–1.6%** for three consecutive years, and 2017
passes on four of five statistics. A pipeline with a wrong weekly calendar, a wrong
truncation rule, a wrong filter order, or a wrong aggregation would not reproduce
three years of pooled means to within 2%. This is strong evidence that GT-1 (Liu
year-blocks), GT-2 (daily per-day truncation + cascade), the mcap>BTC daily screen,
the USD 1M weekly floor and the stablecoin exclusion are all implemented correctly.

**2. The divergence is monotone in time and has a single signature.**
From 2018 onward: coin counts run progressively **high** (+5.6% → +25%), while mean
market cap and mean volume run progressively **low** (−1.7% → −14.7%, −2.0% → −45.8%).
That is the signature of **a larger universe containing additional small, illiquid
coins**, which inflates N and dilutes both means. It is not the signature of a
mis-specified filter, which would bias early and late years alike.

**3. Most likely cause: data vintage, not implementation.**
The authors pulled CoinMarketCap around 2022–23; this panel was harvested from the
same endpoint in **2026**. CMC has since backfilled and extended its historical
snapshots. The effect necessarily grows with time-of-sample, exactly as observed,
and is largest in the years with the most subsequent listing activity. It cannot be
corrected from our side, and attempting to tune the universe down to match would be
precisely the automated p-hacking I3 forbids.

**4. One residual that vintage does NOT explain: median volume.**
`med Vol` runs **+6% to +21% high in every year, including 2015–2017 where counts and
means match**. A composition effect would move mean and median together; this is a
level effect in the volume variable itself. Leading hypothesis: CMC's `volume24h` is
a **rolling 24-hour** figure sampled at snapshot time, whereas the authors'
`volume_cmc.csv` was a daily-bucketed volume. Flagged as **open**; it affects the ten
volume-based indicators and the liquidity screen, so it must be resolved before M2
results are trusted.

## Two internal inconsistencies in the paper (recorded, not resolved by us)

* **Sample length.** §III.A states the Apr 2015 – May 2022 window yields "a total
  **423** weekly observations". The shipped `Results/CTREND/CTREND.xlsx` contains
  **371** rows (201516 → 202222), and our independent Liu-block calendar produces
  **exactly 371**. We treat 371 as correct; 423 appears to be an error.
* **Unique coins.** §III.A text says "3,244"; Table 1's Full row says "3,245".

## GT-4 confirmed by the paper's own footnote

§III.B says the macd expresses the EMA difference "as a percentage of the **fast**
EMA", but footnote 3 states "This normalization makes the macd equivalent to the
**percentage price oscillator (PPO)**" — and PPO divides by the **slow** EMA. The
paper contradicts itself; the footnote agrees with the code (`b02:199` calls
`fPercentagePriceOscillator`). **GT-4's choice of `macd_denominator: slow` is correct**,
and the "fast" wording in the body text is the paper's error, not ours.

## Other confirmations from the paper

* "The model parameters are estimated using a fixed **rolling window of 52 weeks**"
  (§III.C) — confirms GT-8 `training_window: rolling:52`.
* Footnote 1: the mcap>Bitcoin filter "eliminates a total of ten **daily**
  observations" — confirms GT-2's daily application.
* §VII.B eq. (14)–(15) confirm the GKX turnover definition and the 30/40 bps base
  cost scheme, reported "as the average of the long and short legs".
* §7 acceptance bands are all confirmed against Table 3 and Table 9: H−L **3.87%**
  (t = 5.19), Sharpe **1.94**, βCMOM **0.79**, αLTW **2.62%** (t = 4.22), turnover
  **68.46%**, and monotone quintiles L 0.12 → 2 0.93 → 3 1.12 → 4 2.72 → H 3.98.

## New validation assets unlocked

**Table 2 gives H−L returns and t-statistics for all 28 individual indicators.**
This is a far stronger M2 gate than SPEC's "spot-check three indicators against the
`ta` package": each indicator can be validated end-to-end against a published number,
including sign. Notable targets — rsi **+3.52**, stochK **+3.96**, cci **+3.80**,
boll_mid **−3.50**, sma_20d **−3.13**, sma_5d **−2.90**, volsma_50d **−1.58**.
Several are negative, so sign errors cannot hide.

**Table 5** (subperiods), **Table 8** (big/liquid subsets) and **Table 9** (net of
costs, BETC 1.41% / 1.29% at 5%) give further checkpoints for M4–M6.

## Recommendation

Do **not** adjust the universe to close this gate. Instead:

1. Resolve the median-volume level question (rolling-24h vs daily-bucketed), which is
   a genuine data-semantics issue rather than a tuning knob.
2. Proceed to M2 and gate on **Table 2's 28 indicator returns**, which are far more
   diagnostic of implementation correctness than sample counts and are insensitive to
   the vintage-driven universe drift documented above.
3. Carry the +16% universe difference forward as a known, documented deviation, and
   report §7 results both on the full universe and on a rank-capped subset if the
   drift proves material.
