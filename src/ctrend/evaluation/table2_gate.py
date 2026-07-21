"""M2 gate — the 28 indicators against the paper's Table 2 (SPEC §6, M2 DoD).

Table 2 (p. 3125-3126) publishes the value-weighted quintile H−L weekly return **and
t-statistic for every individual indicator**. That is a far stronger gate than SPEC's
"spot-check three indicators against the `ta` package": it validates each indicator
end to end — construction, weekly resampling, rank map, and sort — against a
published number.

Crucially **10 of the 28 are negative**, so a sign error cannot hide behind a
plausible magnitude. `sma_20d` is −3.13 and `boll_mid` is −3.50; an implementation
that flipped the ratio direction would produce +3-ish and look perfectly reasonable
in isolation.

Sort mechanics follow `fSingleSortMulti.m`: quintiles on the week-*t* rank, portfolios
value-weighted on week-*t* market cap, held over week *t+1*, with a week voided below
`iMinNumCS = 25` valid coins or `iMinNumAssets = 5` per portfolio. t-statistics are
plain OLS/iid per GT-12, matching the paper.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ctrend.indicators.technical import INDICATORS

log = logging.getLogger("table2")

#: Paper Table 2, H−L mean weekly return in % and its t-statistic.
PAPER_TABLE2: dict[str, tuple[float, float]] = {
    "rsi": (3.52, 5.41), "stochRSI": (1.30, 1.78), "stochK": (3.96, 5.73),
    "stochD": (2.89, 4.06), "cci": (3.80, 5.03),
    "sma_3d": (-0.89, -1.11), "sma_5d": (-2.90, -3.35), "sma_10d": (-2.37, -2.90),
    "sma_20d": (-3.13, -3.80), "sma_50d": (-2.49, -2.88), "sma_100d": (-0.96, -1.12),
    "sma_200d": (0.04, 0.05), "macd": (2.16, 2.50), "macd_diff_signal": (2.25, 2.46),
    "volsma_3d": (-0.21, -0.34), "volsma_5d": (-0.66, -1.09),
    "volsma_10d": (-0.16, -0.21), "volsma_20d": (-0.81, -1.03),
    "volsma_50d": (-1.58, -2.20), "volsma_100d": (-1.68, -2.12),
    "volsma_200d": (-1.54, -2.03), "volmacd": (2.01, 2.38),
    "volmacd_diff_signal": (0.39, 0.46), "chaikin": (1.12, 1.68),
    "boll_low": (-2.08, -2.28), "boll_mid": (-3.50, -4.25),
    "boll_high": (-2.41, -3.01), "boll_width": (0.67, 0.72),
}
assert set(PAPER_TABLE2) == set(INDICATORS)

MIN_CS = 25       # iMinNumCS
MIN_ASSETS = 5    # iMinNumAssets
N_Q = 5


def _matlab_quantile(x: np.ndarray, qs: np.ndarray) -> np.ndarray:
    """MATLAB `quantile(..., 'Method','exact')`: (i-0.5)/n plotting positions.

    Not `numpy.percentile`'s default, and the breakpoints differ enough to move
    coins between quintiles in small cross-sections.
    """
    x = np.sort(np.asarray(x, dtype="float64"))
    n = len(x)
    if n == 0:
        return np.full(len(qs), np.nan)
    pos = (np.arange(1, n + 1) - 0.5) / n
    return np.interp(qs, pos, x, left=x[0], right=x[-1])


def _hl_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Weekly H−L return for one indicator, value-weighted quintiles."""
    out: dict[int, float] = {}
    for wk, g in df.groupby("week_id", sort=True):
        s = g[[col, "fwd_ret", "market_cap"]].dropna()
        s = s[s["market_cap"] > 0]
        if len(s) < MIN_CS:
            continue
        cuts = _matlab_quantile(s[col].to_numpy(), np.linspace(0, 1, N_Q + 1))
        # Lowest bucket closed on both sides, the rest left-open (fSingleSortMulti).
        b = np.searchsorted(cuts[1:-1], s[col].to_numpy(), side="left")
        s = s.assign(q=b)
        lo, hi = s[s.q == 0], s[s.q == N_Q - 1]
        if len(lo) < MIN_ASSETS or len(hi) < MIN_ASSETS:
            continue
        rl = np.average(lo["fwd_ret"], weights=lo["market_cap"])
        rh = np.average(hi["fwd_ret"], weights=hi["market_cap"])
        out[int(wk)] = rh - rl
    return pd.Series(out, name=col).sort_index()


def run(signals: str = "data/curated/signals_weekly.parquet",
        weekly: str = "data/curated/panel_weekly.parquet",
        start: int = 201516, end: int = 202222,
        complete_case: bool = False) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    cc = "AND s.complete_case" if complete_case else ""
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, market_cap, weekly_return,
                   lead(weekly_return) OVER (PARTITION BY coin_id ORDER BY week_id) AS fwd_ret,
                   lead(week_id)       OVER (PARTITION BY coin_id ORDER BY week_id) AS nxt
            FROM read_parquet('{weekly}')
        )
        SELECT s.*, p.market_cap, p.fwd_ret
        FROM read_parquet('{signals}') s
        JOIN p USING (coin_id, week_id)
        WHERE p.fwd_ret IS NOT NULL
          AND s.week_id BETWEEN {start} AND {end}
          {cc}
    """).df()
    con.close()
    log.info("panel for sorts: %s coin-weeks, %s weeks",
             f"{len(df):,}", f"{df.week_id.nunique():,}")

    rows = []
    for name in INDICATORS:
        hl = _hl_series(df, name)
        if len(hl) < 30:
            rows.append({"indicator": name, "n_weeks": len(hl), "mean_pct": np.nan,
                         "t_stat": np.nan})
            continue
        m = float(hl.mean()) * 100
        t = float(hl.mean() / (hl.std(ddof=1) / np.sqrt(len(hl))))  # GT-12: OLS/iid
        pm, pt = PAPER_TABLE2[name]
        rows.append({
            "indicator": name, "n_weeks": len(hl),
            "mean_pct": m, "paper_mean": pm, "diff": m - pm,
            "t_stat": t, "paper_t": pt,
            "sign_ok": bool(np.sign(m) == np.sign(pm)) if pm != 0 else True,
        })
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--signals", default="data/curated/signals_weekly.parquet")
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--complete-case", action="store_true",
                   help="restrict to coin-weeks with all 28 indicators (paper-faithful)")
    p.add_argument("--out", type=Path, default=Path("reports/m2_table2_gate.csv"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    res = run(a.signals, a.weekly, complete_case=a.complete_case)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(a.out, index=False)

    ok = int(res["sign_ok"].sum())
    print(res.to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    print(f"\nsign agreement: {ok}/{len(res)}")
    print(f"median |diff| : {res['diff'].abs().median():.2f} pp")
    corr = res[["mean_pct", "paper_mean"]].dropna().corr().iloc[0, 1]
    print(f"corr(mine, paper) across the 28: {corr:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
