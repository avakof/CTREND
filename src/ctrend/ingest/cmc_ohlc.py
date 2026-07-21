"""Per-coin daily OHLC backfill (SPEC §4.2 — the four high/low indicators).

`stochK`, `stochD`, `cci` and `chaikin` need daily highs and lows, which the
listings-snapshot endpoint used by `cmc_snapshots.py` does not carry. This module
fetches them per coin from CMC's historical endpoint.

**Measured survivorship problem — read before using this data.** Census over all
3,799 panel coins, after re-probing every miss at low concurrency to rule out
rate-limit false negatives (116 of the first pass's "empty" results were HTTP 429s,
and 55 coins recovered on the slower re-probe):

    alive coins     99.1% of coins, 99.3% of coin-weeks
    DELISTED coins  50.5% of coins, 59.3% of coin-weeks
    TOTAL           68.9% of coins, 82.2% of coin-weeks

CMC has purged per-coin OHLC for roughly 40% of delisted coin-weeks since the authors
pulled their data in 2022-23. Because `b05CreateCTREND.m:115` requires complete cases
across all 28 indicators, a missing high/low does not merely degrade four indicators
-- it removes the coin-week from CTREND altogether. Applying the paper's design
literally to this data drops **48,202 coin-weeks, 47,182 of them (97.9%) delisted**,
reintroducing precisely the survivorship bias the study depends on avoiding and
biasing the H-L spread upward through the short leg.

Consequently the curated OHLC layer records coverage explicitly, and the decision of
what to do with uncovered coin-weeks is a flagged configuration choice logged in
DECISIONS.md -- never a silent deletion.

Secondary source for the early window: the Gandal/Hamrick/Moore/Vasek CC0 panel
(doi:10.7910/DVN/JPEF8T), a 2018-vintage CMC scrape that still carries OHLC for coins
CMC has since purged. It spans only weeks <= 201806 (~10% of our panel) and matches
62-74% of our symbols there, so it narrows the gap without closing it.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd

URL = "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/historical"
USD = 2781  # CMC convertId for USD
OUT = Path("data/raw/cmc_ohlc")

log = logging.getLogger("ohlc")


#: The endpoint silently DOWN-SAMPLES to fit a ~732-point cap rather than truncating
#: or erroring. A 2012-2023 request for BTC returns 732 rows at 6-day spacing (725
#: gaps of exactly 6 days); the same range in one-year slices returns true daily bars.
#: Six-daily data is useless for 14- and 20-day indicator windows, and the silence is
#: the dangerous part -- it yields plausible, wrong indicators. Chunk below the cap.
MAX_POINTS = 732
CHUNK_DAYS = 720  # just inside the cap: verified to return 721 true daily bars.
#: 360 also works but doubles the request count, which is what tripped CMC's
#: CloudFront rate limit on the first attempt.


def _fetch_window(coin_id: int, t0: int, t1: int, *, delay: float, retries: int = 3):
    url = f"{URL}?id={coin_id}&convertId={USD}&timeStart={t0}&timeEnd={t1}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                payload = json.load(r)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                log.warning("coin %s window failed: %s", coin_id, str(exc)[:60])
                raise _WindowFailed(coin_id) from exc
            time.sleep(delay * (2**attempt) + 1.0)

    rows = []
    for q in (payload.get("data") or {}).get("quotes") or []:
        v = q.get("quote") or {}
        if v.get("high") is None:
            continue
        rows.append({
            "coin_id": coin_id,
            "date": pd.Timestamp(v["timestamp"]).normalize().tz_localize(None),
            "open": v.get("open"), "high": v.get("high"),
            "low": v.get("low"), "close": v.get("close"),
            "volume_ohlc": v.get("volume"), "market_cap_ohlc": v.get("marketCap"),
        })
    return rows


class _WindowFailed(Exception):
    """A chunk could not be retrieved after retries.

    Raised rather than swallowed: chunked fetching means a throttled window leaves a
    *hole* in the middle of an otherwise-complete series. Writing that file would
    record a partial coin as if it were whole, and the gap would silently corrupt
    every rolling indicator that spans it. The coin is left unwritten so the resume
    logic re-fetches it.
    """


def fetch_coin(coin_id: int, t0: int, t1: int, *, delay: float, retries: int = 3):
    """True daily OHLC over [t0, t1], fetched in sub-cap chunks and de-duplicated."""
    rows, span = [], CHUNK_DAYS * 86400
    a = t0
    while a <= t1:
        b = min(a + span, t1)
        rows.extend(_fetch_window(coin_id, a, b, delay=delay, retries=retries))
        a = b + 86400
        if a <= t1:
            time.sleep(delay)
    if not rows:
        return []
    df = pd.DataFrame(rows).drop_duplicates(subset=["coin_id", "date"])
    return df.sort_values("date").to_dict("records")


def harvest(panel: str, out: Path, *, delay: float, force: bool = False,
            workers: int = 4) -> None:
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    coins = con.execute(f"""
        SELECT coin_id, min(week_id) AS w0, max(week_id) AS w1, count(*) AS cw
        FROM read_parquet('{panel}') GROUP BY 1 ORDER BY cw DESC
    """).fetchall()
    log.info("panel coins to backfill: %d", len(coins))

    # Resume must check COVERAGE, not mere existence. A cached file was fetched
    # against whatever panel existed at the time; when the panel is later extended
    # (e.g. the M6 out-of-sample window), every surviving coin's file stops at the
    # old sample edge. Treating those as "done" silently truncates high/low for
    # exactly the coins that survive -- ETH's cache ended 2022-06-05 and OOS H/L
    # coverage collapsed to 7-19% before this check was added.
    def _needs_fetch(cid: int, w1: int) -> bool:
        f = out / f"{cid}.parquet"
        if force or not f.exists():
            return True
        try:
            d = pd.read_parquet(f, columns=["date"])
        except Exception:  # noqa: BLE001 - unreadable cache is a re-fetch
            return True
        if d.empty:
            return False  # a recorded genuine miss; re-probing is handled separately
        need = (pd.Timestamp(year=w1 // 100, month=1, day=1)
                + pd.Timedelta(days=7 * (w1 % 100 - 1)))
        return d["date"].max() < need - pd.Timedelta(days=7)

    todo = [(int(cid), w0, w1) for cid, w0, w1, _ in coins if _needs_fetch(int(cid), w1)]
    stale = sum(1 for cid, _, w1, _ in coins
                if (out / f"{int(cid)}.parquet").exists() and _needs_fetch(int(cid), w1))
    log.info("to fetch: %d  (of which %d are cached but STALE — panel now extends "
             "past their coverage)", len(todo), stale)

    def one(job):
        cid, w0, w1 = job
        # Pad only what the warm-up actually needs: the longest window is the
        # 200-day SMA, so ~260 days before the coin's first panel week. Nothing
        # after its last week is used. Padding a full calendar year either side
        # (the first version) roughly doubled the request count for no benefit.
        def _wk_date(w):
            return pd.Timestamp(year=w // 100, month=1, day=1) + pd.Timedelta(days=7 * (w % 100 - 1))
        t0 = int((_wk_date(w0) - pd.Timedelta(days=260)).timestamp())
        t1 = int((_wk_date(w1) + pd.Timedelta(days=8)).timestamp())
        try:
            rows = fetch_coin(cid, t0, t1, delay=delay)
        except _WindowFailed:
            return None  # incomplete: write nothing, retry on the next run
        cols = ["coin_id", "date", "open", "high", "low", "close",
                "volume_ohlc", "market_cap_ohlc"]
        df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)
        # An empty file is written deliberately: a miss must be *recorded* so
        # coverage is measurable rather than inferred from absence.
        df.to_parquet(out / f"{cid}.parquet", index=False, compression="zstd")
        time.sleep(delay)
        return bool(rows)

    # Modest concurrency: sequential fetching runs ~5h for 3.8k coins because each
    # request spans several years of daily bars. Four workers keeps the observed
    # request rate near that of the (error-free) snapshot harvest.
    n_ok = n_empty = n_partial = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, got in enumerate(pool.map(one, todo), 1):
            if got is None:
                n_partial += 1
                continue
            n_ok += got
            n_empty += not got
            if i % 200 == 0:
                log.info("%d/%d  with_ohlc=%d  empty=%d", i, len(todo), n_ok, n_empty)

    log.info("DONE. with OHLC=%d  without=%d  INCOMPLETE(retry)=%d -> %s",
             n_ok, n_empty, n_partial, out)
    con.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", default="data/curated/panel_weekly.parquet")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--delay", type=float, default=0.25)
    p.add_argument("--force", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    harvest(a.panel, a.out, delay=a.delay, force=a.force, workers=a.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
