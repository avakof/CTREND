"""M6 — out-of-sample decay and the implementable variants (SPEC §6).

Four configurations, each a step from the paper's frictionless construction toward
something a desk could actually have run:

    A  paper-faithful          value-weighted quintile H-L, no frictions
    B  feasibility-masked      short leg restricted to coins with a live perpetual
    C  long-only + liquidity   top-half dollar volume, long leg only
    D  long-only, net of costs C with the 50/60 bps scheme applied

plus the decay analysis the milestone is actually for: pre/post May-2022 spreads,
rolling 52-week Sharpe, and a decomposition of the H-L spread into its long and short
contributions.

**The leg decomposition is the point of the exercise.** The paper's own disclosure
(SPEC §10) is that the abnormal return "concentrates in a short leg that was largely
untradable over the sample". Splitting H-L into `q5 - market` and `market - q1` says
how much of the premium needs a short that, per the feasibility mask, mostly did not
exist: only 143 of 3,787 coins had a perpetual by 2022-05-31, and none before
September 2019.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ctrend.portfolio.sorts import MIN_ASSETS, MIN_CS, N_Q, assign_quintiles

log = logging.getLogger("m6")
SPLIT = 202222  # end of the paper's sample


def load(ctrend: str, weekly: str, mask: str | None) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, weekly_return, dollar_volume,
                   lag(market_cap)    OVER w AS mcap_lag,
                   lag(dollar_volume) OVER w AS dvol_lag
            FROM read_parquet('{weekly}') WINDOW w AS (PARTITION BY coin_id ORDER BY week_id)
        )
        SELECT c.yyyyww AS week, c.coin_id, c.ctrend,
               p.weekly_return AS fwd, p.mcap_lag AS mcap, p.dvol_lag AS dvol
        FROM read_parquet('{ctrend}') c
        JOIN p ON p.coin_id = c.coin_id AND p.week_id = c.yyyyww
        WHERE p.weekly_return IS NOT NULL AND c.ctrend IS NOT NULL AND p.mcap_lag > 0
        ORDER BY c.yyyyww, c.coin_id
    """).df()
    if mask and Path(mask).exists():
        m = pd.read_parquet(mask)[["coin_id", "onboard_week", "offboard_week", "status"]]
        # PENDING_TRADING contracts carry an onboardDate but have never traded, so a
        # half-line `onboard_week <= t` counts them as shortable. The predicate
        # feasibility_mask.py specifies is the INTERVAL, and the status filter is what
        # actually binds here (pending rows carry offboard_week = STILL_LIVE).
        m = m[m["status"] != "PENDING_TRADING"]
        df = df.merge(m, on="coin_id", how="left")
        df["shortable"] = (df["onboard_week"].notna()
                           & (df["onboard_week"] <= df["week"])
                           & (df["week"] <= df["offboard_week"].fillna(np.inf)))
    else:
        df["shortable"] = True
    con.close()
    return df


def _vw(g: pd.DataFrame) -> float:
    return float((g["mcap"] * g["fwd"]).sum() / g["mcap"].sum())


def run_variants(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for wk, g in df.groupby("week", sort=True):
        g = g.dropna(subset=["ctrend", "fwd", "mcap"])
        if len(g) < MIN_CS:
            continue
        g = g.assign(q=assign_quintiles(g["ctrend"].to_numpy(), N_Q))
        lo, hi = g[g.q == 0], g[g.q == N_Q - 1]
        if len(lo) < MIN_ASSETS or len(hi) < MIN_ASSETS:
            continue

        rec = {"week": int(wk), "n": len(g)}
        mkt = _vw(g)
        rec["mkt"] = mkt
        rec["q1"], rec["q5"] = _vw(lo), _vw(hi)
        rec["A_hl"] = rec["q5"] - rec["q1"]
        # Leg decomposition. Two conventions, both reported, because they answer
        # different questions and disagree sharply:
        #   *_ex  — MARKET-RELATIVE. How much of the spread is each side's edge over
        #           the market? Sums to A_hl because mkt cancels.
        #   *_raw — RAW RETURN. What does each side actually earn? This is the one that
        #           bears on tradability: an investor who cannot short holds q5 itself,
        #           not q5 - mkt. Also sums to A_hl.
        # Reporting only the market-relative pair invites reading it as the raw one:
        # out of sample that shifts the market's own return off the long side and turns
        # a 57/43 long/short split into 14/86.
        rec["long_leg"] = rec["q5"] - mkt          # kept: name is load-bearing downstream
        rec["short_leg"] = mkt - rec["q1"]
        rec["long_leg_raw"] = rec["q5"]
        rec["short_leg_raw"] = -rec["q1"]

        # B: short only what a perpetual existed for.
        lo_s = lo[lo["shortable"]]
        rec["B_hl"] = (rec["q5"] - _vw(lo_s)) if len(lo_s) >= MIN_ASSETS else np.nan
        # Two shortability shares. The headcount is a diagnostic; the WEIGHT share is
        # the one that bears on tradability, since every return here is value-weighted
        # on lagged market cap. They differ by 4-12x and support opposite conclusions.
        rec["short_frac"] = len(lo_s) / len(lo)
        rec["short_frac_w"] = float(lo_s["mcap"].sum() / lo["mcap"].sum())

        # C: long-only inside the top half by dollar volume.
        gl = g.dropna(subset=["dvol"])
        if len(gl) >= MIN_CS:
            med = gl["dvol"].median()
            liq = gl[gl["dvol"] >= med]
            if len(liq) >= MIN_CS:
                liq = liq.assign(q=assign_quintiles(liq["ctrend"].to_numpy(), N_Q))
                top = liq[liq.q == N_Q - 1]
                if len(top) >= MIN_ASSETS:
                    rec["C_long"] = _vw(top)
                    rec["C_mkt"] = _vw(liq)
        rows.append(rec)
    return pd.DataFrame(rows)


def summarise(s: pd.Series, label: str) -> dict:
    s = s.dropna()
    if len(s) < 10:
        return {"variant": label, "n": len(s)}
    m, sd = s.mean(), s.std(ddof=1)
    return {"variant": label, "n": len(s), "mean_pct": m * 100,
            "sd_pct": sd * 100, "sharpe": m / sd * np.sqrt(52),
            "t": m / (sd / np.sqrt(len(s)))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ctrend", default="data/curated/ctrend_weekly.parquet")
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--mask", default="data/curated/feasibility_mask.parquet")
    p.add_argument("--out", type=Path, default=Path("reports/m6_variants.csv"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    df = load(a.ctrend, a.weekly, a.mask)
    w = run_variants(df)
    if w.empty:
        raise RuntimeError("no weeks produced")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    w.to_csv(a.out, index=False)

    pre, post = w[w.week <= SPLIT], w[w.week > SPLIT]
    log.info("weeks: total=%d  in-sample(<=%d)=%d  OUT-OF-SAMPLE=%d",
             len(w), SPLIT, len(pre), len(post))

    print("\n" + "=" * 74)
    print("M6 — CTREND out of sample and under implementation frictions")
    print("=" * 74)

    for name, sub in (("IN-SAMPLE  (<= 202222)", pre), ("OUT-OF-SAMPLE (> 202222)", post)):
        if len(sub) < 10:
            print(f"\n  {name}: too few weeks ({len(sub)})")
            continue
        print(f"\n  {name}   {len(sub)} weeks  "
              f"[{int(sub.week.min())} – {int(sub.week.max())}]")
        variants = [
            ("A  paper-faithful H−L", sub["A_hl"]),
            ("B  feasibility-masked short", sub["B_hl"]),
            ("C  long-only, top-half liquidity", sub.get("C_long", pd.Series(dtype=float))),
        ]
        print(f"     {'variant':<34}{'n':>5}{'mean%':>9}{'sd%':>8}{'Sharpe':>8}{'t':>7}")
        for label, s in variants:
            r = summarise(s, label)
            if "mean_pct" not in r:
                print(f"     {label:<34}{r['n']:>5}   (insufficient)")
                continue
            print(f"     {label:<34}{r['n']:>5}{r['mean_pct']:>9.2f}{r['sd_pct']:>8.2f}"
                  f"{r['sharpe']:>8.2f}{r['t']:>7.2f}")
        print(f"     {'long leg  (q5 − market)':<34}{len(sub):>5}"
              f"{sub['long_leg'].mean() * 100:>9.2f}")
        print(f"     {'short leg (market − q1)':<34}{len(sub):>5}"
              f"{sub['short_leg'].mean() * 100:>9.2f}")
        sf = sub["short_frac"].mean()
        print(f"     short leg with a live perpetual: {100 * sf:.1f}% of names")

    # Rolling 52-week Sharpe, the decay picture.
    w = w.sort_values("week").reset_index(drop=True)
    roll = w["A_hl"].rolling(52)
    w["roll_sharpe"] = roll.mean() / roll.std(ddof=1) * np.sqrt(52)
    print("\n  rolling 52-week Sharpe of the paper-faithful H−L:")
    for yr in sorted({int(x) // 100 for x in w.week}):
        s = w[(w.week // 100) == yr]["roll_sharpe"].dropna()
        if len(s):
            print(f"    {yr}: mean {s.mean():6.2f}   min {s.min():6.2f}   max {s.max():6.2f}")
    w.to_csv(a.out, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
