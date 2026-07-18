"""CoinMarketCap daily snapshot harvester (SPEC §4.1, Track A substitute).

The authors' replication package (doi:10.7910/DVN/NTIVT8) ships MATLAB code only;
`b01ReadData.m` expects six `*_cmc.csv` panels that were never redistributable.
This module reconstructs that panel from CMC's public historical listings endpoint,
which returns a point-in-time cross-section for an arbitrary date -- including coins
that later died (verified: BitConnect at rank 26 on 2018-01-07 with $2.33B mcap).

Provenance / limitations, recorded here because they bind downstream analysis:
  * Undocumented internal endpoint. No stability guarantee. Harvest once to parquet;
    never call it live from the research pipeline.
  * CMC terms prohibit redistribution and derivative index creation. The harvested
    panel therefore stays local (data/ is gitignored) and MUST NOT ship in any
    replication package. CC0 sources are cited for anything redistributable.
  * The endpoint carries no high/low. Four of the 28 indicators (stochK, stochD,
    cci, chaikin) need them; see DECISIONS.md for the handling rule.

Harvest is resumable at month granularity and polite by construction.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

URL = "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical"
PAGE = 5000
DEFAULT_OUT = Path("data/raw/cmc_daily")

# CMC's own history begins here; also the start date used by the authors'
# b01GenerateArtificialData.m, and early enough to warm up the 200-day SMAs.
DEFAULT_START = date(2013, 4, 28)
DEFAULT_END = date(2022, 5, 31)  # replication window close (SPEC §4.1)

log = logging.getLogger("cmc")

KEEP = [
    "id", "name", "symbol", "slug", "cmcRank",
    "circulatingSupply", "totalSupply", "maxSupply", "dateAdded",
]
QUOTE = ["price", "marketCap", "volume24h"]


def fetch_day(session: requests.Session, day: date, *, delay: float, retries: int = 4) -> pd.DataFrame:
    """One point-in-time cross-section. Paginates; returns empty frame if absent."""
    rows: list[dict] = []
    start = 1
    while True:
        params = {"date": day.isoformat(), "start": start, "limit": PAGE, "convert": "USD"}
        for attempt in range(retries):
            try:
                r = session.get(URL, params=params, timeout=60)
                if r.status_code == 200:
                    break
                raise requests.HTTPError(f"HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001 - retry on any transport failure
                if attempt == retries - 1:
                    raise
                sleep = delay * (2 ** attempt) + 1.0
                log.warning("%s start=%s attempt %d failed (%s); retrying in %.1fs",
                            day, start, attempt + 1, exc, sleep)
                time.sleep(sleep)

        payload = r.json().get("data") or []
        if not payload:
            break
        for c in payload:
            q = (c.get("quotes") or [{}])[0]
            rec = {k: c.get(k) for k in KEEP}
            rec.update({k: q.get(k) for k in QUOTE})
            tags = c.get("tags") or []
            # CMC tags drive the stablecoin exclusion, a baseline filter in the
            # authors' b05CreateCTREND.m:62-74 that SPEC §4.1 omits entirely.
            rec["is_stablecoin"] = any("stablecoin" in str(t).lower() for t in tags)
            rec["tags"] = ",".join(str(t) for t in tags)
            rec["date"] = day
            rows.append(rec)
        if len(payload) < PAGE:
            break
        start += PAGE
        time.sleep(delay)

    return pd.DataFrame(rows)


def month_path(out: Path, day: date) -> Path:
    return out / f"{day.year}" / f"{day:%Y-%m}.parquet"


def harvest(start: date, end: date, out: Path, *, delay: float, force: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "ctrend-research/0.1"})

    # Group the range by calendar month so a crash costs at most one month.
    day = start
    months: dict[tuple[int, int], list[date]] = {}
    while day <= end:
        months.setdefault((day.year, day.month), []).append(day)
        day += timedelta(days=1)

    total_rows = 0
    for (yr, mo), days in sorted(months.items()):
        path = month_path(out, days[0])
        if path.exists() and not force:
            existing = pd.read_parquet(path, columns=["date"])
            if existing["date"].nunique() >= len(days):
                log.info("%04d-%02d complete (%d days), skipping", yr, mo, existing["date"].nunique())
                total_rows += len(existing)
                continue

        path.parent.mkdir(parents=True, exist_ok=True)
        frames = []
        t0 = time.time()
        for d in days:
            df = fetch_day(session, d, delay=delay)
            if not df.empty:
                frames.append(df)
            time.sleep(delay)

        if not frames:
            log.warning("%04d-%02d returned no data at all", yr, mo)
            continue
        month_df = pd.concat(frames, ignore_index=True)
        month_df["date"] = pd.to_datetime(month_df["date"])
        month_df.to_parquet(path, index=False, compression="zstd")
        total_rows += len(month_df)
        log.info("%04d-%02d  days=%d  rows=%-8d coins=%-5d  %.0fs  (cum %.2fM)",
                 yr, mo, month_df["date"].nunique(), len(month_df),
                 month_df["id"].nunique(), time.time() - t0, total_rows / 1e6)

    log.info("DONE. total rows=%s -> %s", f"{total_rows:,}", out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    p.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--delay", type=float, default=0.30, help="seconds between requests")
    p.add_argument("--force", action="store_true", help="re-fetch months already on disk")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    harvest(a.start, a.end, a.out, delay=a.delay, force=a.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
