"""Short-side feasibility mask (ambiguity A4, SPEC §6 M6).

    "a coin is shortable in week *t* only if a borrow/perp venue existed then"

Built from Binance USDT-M perpetual `onboardDate`, which states exactly when each
contract became tradable, and — for contracts no longer trading — the last available
daily bar, which bounds when it stopped.

**Why this matters more than it looks.** Only 127 perpetual contracts had onboarded by
2022-05-31 (160 panel coins under the ticker join below) and the first (BTC) only in
**September 2019**, against a paper universe averaging 800-1,600 coins per week. From
2015-03-11 to 2019-11-25 — 4.71 years, most of the replication sample — no coin in the
bottom quintile was shortable at all. Over the paper window the short book is 0.94% of
names and 11.37% of market-cap weight. That is the concrete content of the standing
disclosure in SPEC §10 that the abnormal return "concentrates in a short leg that was
largely untradable over the sample".

That disclosure is about the *paper window*, and it does not carry to the extension.
Out of sample the short book is 14.69% of names but **53.09%** of market-cap weight, and
over the last 52 weeks 26.34% / **62.01%**. Every return here is value-weighted, so the
weight share is the one that bears on tradability: out of sample the majority of the
short book by dollar weight was shortable. Do not quote the headcount share as if it
were the tradable fraction.

**A survivorship channel, and it works against the strategy.** `exchangeInfo` returns
only contracts that exist *today*. Every perpetual Binance has fully removed is silently
absent, so a coin with a live perp from 2022-24 that was later delisted reads as
never-shortable. This can only *shrink* the constructed shortable set. (An earlier
version of this docstring called the resulting universe an "upper bound on the shortable
universe" and described the channel as flattering the strategy. That is retracted: the
direction was backwards. Survivorship in `exchangeInfo` biases measured shortability
*down*, which understates how tradable the short leg was.) Three mitigations, none of
which fully closes it:

  1. `--snapshot` pins the response to disk. An experiment must not depend on a mask
     that silently changes between runs.
  2. `status` is retained and `offboard_week` recorded for contracts no longer trading,
     so the predicate is the interval `onboard_week <= t <= offboard_week` rather than a
     half-line. This recovers the contracts still visible; it cannot recover those
     removed entirely. `status` is written through rather than filtered here: the three
     panel coins whose only contract is `PENDING_TRADING` (announced, never traded) are
     dropped downstream in `evaluation/m6_variants.py`, which is what takes the matched
     set from 817 coins to the 814 quoted in `reports/m6_decay_report.md` §3.
  3. The residual bias is declared, not buried. On this channel any result built on the
     mask is a *lower* bound on the shortable universe.

**Conservative in the same direction, for a second reason.** Perpetuals are not the only
way to short — margin borrow and OTC existed for some names — but historical borrow
availability is not publicly reconstructible whereas perp onboard dates are exact. This
too biases the mask *down*.

**The one channel that biases up: bare ticker matching.** Shortability is assigned by
`upper(perp.base) = panel.sym` — a ticker string join, with no market-cap or identity
check. 145 perp tickers are shared by ~342 panel coins, so up to ~197 coins are marked
shortable purely by ticker collision with a larger namesake. Deduplicating to the
largest coin per ticker cuts the out-of-sample headcount share from 14.7% to 13.6%.

So the mask is bounded in both directions, but not symmetrically: two mechanisms
(`exchangeInfo` survivorship, non-perp venues) push it down and one (ticker collision)
pushes it up. It is an estimate with error bars on both sides — **it is not exact**, and
no report may describe it as exact. Both directions belong in any report that uses it.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

FAPI = "https://fapi.binance.com/fapi/v1/exchangeInfo"
KLINES = "https://fapi.binance.com/fapi/v1/klines"
OUT = Path("data/curated/feasibility_mask.parquet")
SNAPSHOT = Path("data/raw/binance_exchange_info.json")
log = logging.getLogger("feasibility")

#: Sentinel for "still trading" — larger than any real Liu week id.
STILL_LIVE = 999999


def _liu_week(ts: pd.Timestamp) -> int:
    doy = ts.dayofyear
    return int(ts.year) * 100 + int(min(52, (doy - 1) // 7 + 1))


def _load_exchange_info(snapshot: Path, refresh: bool) -> dict:
    """Read the pinned snapshot, fetching only if absent or explicitly refreshed."""
    if snapshot.exists() and not refresh:
        log.info("using pinned snapshot %s", snapshot)
        return json.loads(snapshot.read_text())
    log.info("fetching %s", FAPI)
    with urllib.request.urlopen(FAPI, timeout=60) as r:
        payload = json.load(r)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(payload))
    log.info("snapshot written to %s", snapshot)
    return payload


def _last_bar_week(symbol: str, delay: float = 0.25) -> int | None:
    """Week of the last daily bar — bounds when a non-trading contract stopped."""
    url = f"{KLINES}?symbol={symbol}&interval=1d&limit=1500"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            bars = json.load(r)
    except Exception as exc:  # noqa: BLE001
        log.warning("klines failed for %s: %s", symbol, str(exc)[:50])
        return None
    finally:
        time.sleep(delay)
    if not bars:
        return None
    return _liu_week(pd.to_datetime(bars[-1][0], unit="ms"))


def fetch_perps(snapshot: Path, *, refresh: bool = False,
                resolve_offboard: bool = True) -> pd.DataFrame:
    d = _load_exchange_info(snapshot, refresh)
    rows = []
    for x in d["symbols"]:
        if x.get("contractType") != "PERPETUAL":
            continue
        ob = pd.to_datetime(x.get("onboardDate"), unit="ms", errors="coerce")
        if pd.isna(ob):
            continue
        rows.append({"base": x["baseAsset"], "symbol": x["symbol"],
                     "onboard": ob, "onboard_week": _liu_week(ob),
                     "status": x["status"]})
    f = pd.DataFrame(rows)

    # Contracts still TRADING have no end. For the rest, bound the interval with the
    # last daily bar rather than pretending they were never shortable.
    f["offboard_week"] = STILL_LIVE
    dead = f[f["status"] != "TRADING"]
    if resolve_offboard and len(dead):
        log.info("resolving offboard week for %d non-trading contracts ...", len(dead))
        for i, row in dead.iterrows():
            wk = _last_bar_week(row["symbol"])
            if wk is not None:
                f.loc[i, "offboard_week"] = wk
        n_res = int((f["offboard_week"] != STILL_LIVE).sum())
        log.info("  resolved %d", n_res)

    # A base asset can have several contracts; shortability spans the union, so take
    # the earliest onboarding and the latest offboarding.
    return (f.groupby("base", as_index=False)
             .agg(onboard_week=("onboard_week", "min"),
                  offboard_week=("offboard_week", "max"),
                  status=("status", "first")))


def build(weekly: str = "data/curated/panel_weekly.parquet", out: Path = OUT,
          snapshot: Path = SNAPSHOT, *, refresh: bool = False,
          resolve_offboard: bool = True) -> dict:
    perps = fetch_perps(snapshot, refresh=refresh, resolve_offboard=resolve_offboard)
    log.info("binance perpetuals: %d base assets, first onboard week %d",
             len(perps), int(perps["onboard_week"].min()))

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.register("perps", perps)
    m = con.execute(f"""
        WITH panel AS (
            SELECT DISTINCT coin_id, upper(symbol) AS sym FROM read_parquet('{weekly}')
        )
        SELECT p.coin_id, p.sym AS symbol, pe.onboard_week, pe.offboard_week, pe.status
        FROM panel p JOIN perps pe ON upper(pe.base) = p.sym
    """).df()
    m = m.sort_values("onboard_week").groupby("coin_id", as_index=False).first()

    n_panel = con.execute(
        f"SELECT count(DISTINCT coin_id) FROM read_parquet('{weekly}')").fetchone()[0]
    log.info("panel coins matched to a perpetual: %d of %d (%.1f%%)",
             len(m), n_panel, 100 * len(m) / n_panel)
    n_dead = int((m["offboard_week"] != STILL_LIVE).sum())
    log.info("  of which no longer trading (interval bounded): %d", n_dead)

    out.parent.mkdir(parents=True, exist_ok=True)
    m.to_parquet(out, index=False)
    for cut in (202222, 202352, 202452, 202552):
        live = int(((m["onboard_week"] <= cut) & (m["offboard_week"] >= cut)).sum())
        log.info("  shortable at %d: %d coins", cut, live)
    con.close()
    return {"matched": len(m), "panel_coins": int(n_panel), "offboarded": n_dead}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weekly", default="data/curated/panel_weekly.parquet")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    p.add_argument("--refresh", action="store_true",
                   help="re-fetch and overwrite the snapshot (NOT during an experiment)")
    p.add_argument("--no-offboard", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    build(a.weekly, a.out, a.snapshot, refresh=a.refresh,
          resolve_offboard=not a.no_offboard)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
