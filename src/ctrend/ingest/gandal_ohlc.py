"""Gandal/Hamrick/Moore/Vasek CC0 OHLC layer — the pre-2018 high/low backfill.

Two Harvard Dataverse deposits, both CC0, both 2018/2019-vintage CoinMarketCap
scrapes that still carry daily OHLC for coins CMC has since purged from its
per-coin endpoint:

    coin_data.tab  doi:10.7910/DVN/JPEF8T   1,082 coins   2013-04-28 -> 2018-02-06
    token_data.tab doi:10.7910/DVN/H98LCZ   1,905 tokens  2014-03-20 -> 2019-10-21

They are exactly complementary to the CMC gap: the delisted coins whose OHLC CMC no
longer serves are disproportionately the ones that died early, which is precisely
this window.

**Identity is the hard part, so matches are verified rather than trusted.** Neither
file carries a CMC id (the token file's `id` column is entirely NaN), and the two
use different naming conventions -- ``"NEO (ANS)"`` in the coin file versus a bare
``"Mothership"`` in the token file. Symbols also collide across coins. A wrong match
would silently inject another asset's prices into four indicators, which is worse
than having no high/low at all.

So every candidate match is **validated against the panel's own closes** on
overlapping dates and rejected unless the two series agree. That check is
independent of how the match was proposed, and it doubles as a cross-source
validation of the CMC-derived data we already hold.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

COIN_CSV = "data/raw/gandal_coin_data.csv"
TOKEN_CSV = "data/raw/gandal_token_data.csv"
OUT = Path("data/curated/gandal_ohlc.parquet")

#: A match is accepted only if, over >= MIN_OVERLAP shared dates, the median absolute
#: log price ratio is below MAX_LOG_DEV. Same asset from two scrapes of the same
#: upstream should agree to well under a percent; a different asset will not.
MIN_OVERLAP = 20
MAX_LOG_DEV = 0.02

log = logging.getLogger("gandal")


def _norm(s: str) -> str:
    """Lowercase alphanumeric core of a name, for candidate proposal only."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _load_coins() -> pd.DataFrame:
    d = pd.read_csv(COIN_CSV, low_memory=False)
    # "NEO (ANS)" -> name "NEO", symbol "ANS"
    d["symbol"] = d["market"].str.extract(r"\(([^()]*)\)$")[0]
    d["name"] = d["market"].str.replace(r"\s*\([^()]*\)$", "", regex=True)
    d["date"] = pd.to_datetime(d["date"], format="%d-%b-%y", errors="coerce")
    return d


def _load_tokens() -> pd.DataFrame:
    d = pd.read_csv(TOKEN_CSV, low_memory=False)
    # "BOXX Token [Blockparty]" -> "BOXX Token"; most entries are a bare name.
    d["name"] = d["market"].str.replace(r"\s*\[[^\[\]]*\]$", "", regex=True)
    d["symbol"] = np.nan
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    return d


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).replace({"-": np.nan, "": np.nan}),
        errors="coerce",
    )


def build(panel: str = "data/curated/panel_weekly.parquet",
          daily: str = "data/curated/panel_daily.parquet",
          out: Path = OUT) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    frames = []
    for loader, src in ((_load_coins, "coin"), (_load_tokens, "token")):
        d = loader()
        for c in ("open", "high", "low", "close"):
            d[c] = _numeric(d[c])
        d = d.dropna(subset=["date", "close"])
        d["source"] = src
        d["nname"] = d["name"].map(_norm)
        frames.append(d[["nname", "symbol", "date", "open", "high", "low", "close", "source"]])
    g = pd.concat(frames, ignore_index=True)
    log.info("gandal rows=%s  distinct names=%s", f"{len(g):,}", f"{g.nname.nunique():,}")

    # Candidate proposal: normalized name, plus symbol when the source has one.
    con.execute(f"""
        CREATE TEMP TABLE panel_coins AS
        SELECT DISTINCT coin_id, name, symbol,
               regexp_replace(lower(name), '[^a-z0-9]', '', 'g') AS nname
        FROM read_parquet('{panel}')
    """)
    con.register("g", g)
    cand = con.execute("""
        SELECT DISTINCT p.coin_id, g.nname, g.source
        FROM g JOIN panel_coins p
          ON g.nname = p.nname
         AND (g.symbol IS NULL OR upper(g.symbol) = upper(p.symbol))
    """).df()
    log.info("candidate (coin_id, name) pairs: %s", f"{len(cand):,}")

    # --- verification against the panel's own closes ------------------------
    con.execute(f"""
        CREATE TEMP TABLE pdaily AS
        SELECT coin_id, CAST(date AS DATE) AS date, close
        FROM read_parquet('{daily}') WHERE close IS NOT NULL
    """)
    con.register("cand", cand)
    chk = con.execute(f"""
        SELECT c.coin_id, c.nname, c.source,
               count(*) AS n,
               median(abs(ln(g.close / p.close))) AS dev
        FROM cand c
        JOIN g  ON g.nname = c.nname AND g.source = c.source
        JOIN pdaily p ON p.coin_id = c.coin_id AND p.date = CAST(g.date AS DATE)
        WHERE g.close > 0 AND p.close > 0
        GROUP BY 1, 2, 3
    """).df()

    good = chk[(chk["n"] >= MIN_OVERLAP) & (chk["dev"] <= MAX_LOG_DEV)]
    bad = chk[(chk["n"] >= MIN_OVERLAP) & (chk["dev"] > MAX_LOG_DEV)]
    thin = chk[chk["n"] < MIN_OVERLAP]
    log.info("verified matches=%s  REJECTED(price disagree)=%s  too-thin=%s",
             f"{len(good):,}", f"{len(bad):,}", f"{len(thin):,}")
    if len(bad):
        log.info("  rejected median dev: %.3f (a same-asset match sits near 0)",
                 float(bad["dev"].median()))

    con.register("good", good[["coin_id", "nname", "source"]])
    hl = con.execute("""
        SELECT gd.coin_id, CAST(g.date AS DATE) AS date,
               g.open, g.high, g.low, g.close, g.source
        FROM g JOIN good gd ON g.nname = gd.nname AND g.source = gd.source
        WHERE g.high IS NOT NULL AND g.low IS NOT NULL
    """).df().drop_duplicates(subset=["coin_id", "date"])

    out.parent.mkdir(parents=True, exist_ok=True)
    hl.to_parquet(out, index=False, compression="zstd")
    log.info("gandal OHLC -> %s  rows=%s  coins=%s",
             out, f"{len(hl):,}", f"{hl.coin_id.nunique():,}")
    con.close()
    return {"rows": len(hl), "coins": int(hl.coin_id.nunique()),
            "verified": len(good), "rejected": len(bad), "thin": len(thin)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", default="data/curated/panel_weekly.parquet")
    p.add_argument("--daily", default="data/curated/panel_daily.parquet")
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    build(a.panel, a.daily, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
