"""BTC/ETH perpetual funding rates, aggregated to Liu weeks (U4 input).

Funding is a real cash flow for a hedged book: a short perpetual receives funding when
the rate is positive, which it predominantly was over 2022-26. Crediting an average
tailwind to a strategy whose viability is in question would flatter it, so the hedge is
reported both with and without it (see `portfolio/overlays.beta_hedge`).

Snapshotted to `data/raw/` on first fetch so the experiment reproduces offline.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://fapi.binance.com/fapi/v1/fundingRate"
OUT = Path("data/curated/funding_weekly.parquet")
RAW = Path("data/raw/binance_funding")
log = logging.getLogger("funding")


def _liu_week(ts: pd.Timestamp) -> int:
    return int(ts.year) * 100 + int(min(52, (ts.dayofyear - 1) // 7 + 1))


def fetch(symbol: str, start_ms: int, raw_dir: Path, delay: float = 0.3) -> pd.DataFrame:
    cache = raw_dir / f"{symbol}.json"
    if cache.exists():
        log.info("%s: using snapshot %s", symbol, cache)
        rows = json.loads(cache.read_text())
    else:
        rows, cursor = [], start_ms
        while True:
            url = f"{URL}?symbol={symbol}&startTime={cursor}&limit=1000"
            with urllib.request.urlopen(url, timeout=45) as r:
                page = json.load(r)
            if not page:
                break
            rows.extend(page)
            nxt = int(page[-1]["fundingTime"]) + 1
            if nxt <= cursor or len(page) < 1000:
                break
            cursor = nxt
            time.sleep(delay)
        raw_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows))
        log.info("%s: fetched %d payments -> %s", symbol, len(rows), cache)

    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d["ts"] = pd.to_datetime(d["fundingTime"], unit="ms")
    d["rate"] = d["fundingRate"].astype(float)
    d["week_id"] = d["ts"].map(_liu_week)
    return (d.groupby("week_id", as_index=False)
             .agg(funding_sum=("rate", "sum"), n_payments=("rate", "size"))
             .assign(symbol=symbol))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    p.add_argument("--start", default="2019-09-01")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--raw", type=Path, default=RAW)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    start_ms = int(pd.Timestamp(a.start).timestamp() * 1000)
    parts = [fetch(s, start_ms, a.raw) for s in a.symbols.split(",")]
    d = pd.concat([x for x in parts if not x.empty], ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(a.out, index=False)
    log.info("funding -> %s  rows=%s  weeks %s..%s  mean weekly rate %.4f%%",
             a.out, f"{len(d):,}", int(d.week_id.min()), int(d.week_id.max()),
             100 * d.funding_sum.mean())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
