# M2 gate — the 28 indicators vs the paper's Table 2

Date: 2026-07-19. Source: Fieberg et al., JFQA 60 (2025), Table 2, pp. 3125–3126.
Sample 201516–202222 (370 weeks). Value-weighted quintile H−L on the week-*t* rank,
held over week *t+1*; OLS/iid t-statistics per GT-12.

## RESULT: **PASS**

| statistic | value |
|---|---|
| sign agreement, all 28 | **25/28** |
| **sign agreement, the 23 indicators the paper finds \|t\| ≥ 1.0** | **23/23** |
| median \|difference\| | **0.39 pp** (0.52 pp on the \|t\| ≥ 1 subset) |
| correlation with Table 2 across the 28 | **0.968** |

### The three sign "mismatches" are statistical zeros in the paper itself

| indicator | ours | paper | paper t |
|---|---|---|---|
| `sma_200d` | −0.23 | +0.04 | **0.05** |
| `volsma_3d` | +0.07 | −0.21 | **−0.34** |
| `volsma_10d` | +0.07 | −0.16 | **−0.21** |

Every one has \|t\| ≤ 0.34 in the published table — the paper cannot distinguish these
from zero either, and neither can we. There is no indicator with a genuine published
signal whose sign we get wrong.

This is the property the gate was chosen for: **10 of the 28 published values are
negative**, so a flipped ratio or an inverted rank map would show up immediately as a
+3 where the paper reports −3. `sma_20d` (−3.91 vs −3.13) and `boll_mid` (−4.30 vs
−3.50) both come through with the right sign and magnitude.

### Closest agreements

`sma_100d` −1.01 vs −0.96 · `boll_high` −2.30 vs −2.41 · `boll_width` 0.71 vs 0.67 ·
`chaikin` 1.25 vs 1.12 · `rsi` 3.40 vs 3.52 · `macd` 1.97 vs 2.16

### Largest residuals

`stochRSI` 3.03 vs 1.30 · `macd_diff_signal` 3.22 vs 2.25 · `volsma_200d` −0.60 vs
−1.54. Given the M1 finding that our universe runs ~16% larger than the authors' from
2018 on (a CMC data-vintage effect), residuals of this size on individual indicators
are expected; the sign and rank structure is what this gate tests.

### The volume-family concern is NOT confirmed

M1 flagged that median volume runs +6–21% high in every year and warned that the ten
volume indicators might therefore be untrustworthy. The gate does not bear that out:

    mean |diff|, volume family : 0.46 pp
    mean |diff|, price family  : 0.50 pp

The volume indicators track Table 2 *slightly better* than the price indicators. The
median-volume level difference remains unexplained, but it is not visibly degrading
the indicators built on it. Downgraded from "blocks trusting the volume group" to
"open, low priority".

## Bug found and fixed by this gate

The first run produced `inf` in 11 of 28 rows and a nonsensical `median |diff| = inf`.
Cause: CMC reports `0.0` for sub-denormal meme-token prices, and `close = 0` makes the
daily return `0/0` and every `sma_Xd = SMA(close)/close` infinite. Because ranks are
*relative*, a single infinity displaces every other coin in that week — corrupting a
whole cross-section rather than one cell.

Fixed upstream: a non-positive price is now treated as a data error at ingest, exactly
as `b01ReadData.m:59-62` treats a non-positive market cap. 123 coin-weeks with
non-finite returns → **0**; panel 270,180 → 269,576 rows. A defensive guard in
`indicators/pipeline.py` now logs and neutralises any recurrence rather than ranking it.

Note the correlation was 0.962 *even with* the infinities present — a reminder that a
plausible-looking headline number can coexist with a serious defect, which is why the
sign structure and the per-indicator residuals matter more than the summary statistic.

## Coverage context

Combined CMC + Gandal high/low coverage: **alive 99.4%, delisted 76.9%, total 89.8%**.
Complete-case (all 28 non-NaN) is **87.4%** of coin-weeks. This gate ran on the full
panel; the complete-case restriction is available via `--complete-case` for the
paper-faithful track.
