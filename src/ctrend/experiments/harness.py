"""Build, tune and evaluate the upgrade configurations.

Every configuration is a weekly H-L return series. `build_series` is the single place
that turns (universe, signal, sort settings, overlays) into one, so a configuration is
data, not code, and the tuning and evaluation paths cannot drift apart.

The freeze is mechanical rather than a matter of discipline: `tune` writes the chosen
parameters plus an integrity hash, and `evaluate` exposes no parameter arguments at
all, so there is no way to re-tune from the evaluation entry point.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ctrend.experiments.windows import EVAL_END, EVAL_START, TUNE_END, TUNE_START
from ctrend.portfolio.overlays import beta_hedge, ewma_signal, vol_target
from ctrend.portfolio.sorts import sort_portfolios

log = logging.getLogger("harness")
FROZEN = Path("configs/frozen_params.json")

BASE_CTREND = "data/curated/ctrend_weekly_stab.parquet"
U1_CTREND = "data/curated/ctrend_weekly_u1_stab.parquet"
WEEKLY = "data/curated/panel_weekly.parquet"
FUNDING = "data/curated/funding_weekly.parquet"


def load_panel(ctrend: str, signal_col: str = "ctrend") -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    df = con.execute(f"""
        WITH p AS (
            SELECT coin_id, week_id, weekly_return,
                   lag(market_cap)    OVER w AS mcap_lag,
                   lag(dollar_volume) OVER w AS dvol_lag
            FROM read_parquet('{WEEKLY}') WINDOW w AS (PARTITION BY coin_id ORDER BY week_id)
        )
        SELECT c.yyyyww AS week, c.coin_id, c."{signal_col}" AS sig,
               p.weekly_return AS fwd, p.mcap_lag AS mcap, p.dvol_lag AS dvol
        FROM read_parquet('{ctrend}') c
        JOIN p ON p.coin_id = c.coin_id AND p.week_id = c.yyyyww
        WHERE p.weekly_return IS NOT NULL AND c."{signal_col}" IS NOT NULL
          AND p.mcap_lag > 0
    """).df()
    con.close()
    return df


def market_series() -> pd.Series:
    con = duckdb.connect()
    d = con.execute(f"""
        WITH p AS (SELECT coin_id, week_id, weekly_return,
                          lag(market_cap) OVER (PARTITION BY coin_id ORDER BY week_id) AS m
                   FROM read_parquet('{WEEKLY}'))
        SELECT week_id AS week, sum(m * weekly_return) / sum(m) AS mkt
        FROM p WHERE m > 0 AND weekly_return IS NOT NULL GROUP BY 1 ORDER BY 1
    """).df()
    con.close()
    return d.set_index("week")["mkt"]


def funding_series() -> pd.Series | None:
    if not Path(FUNDING).exists():
        return None
    f = pd.read_parquet(FUNDING)
    return f.groupby("week_id")["funding_sum"].mean()


def build_series(spec: dict, mkt: pd.Series, fund: pd.Series | None) -> pd.DataFrame:
    """One configuration -> its weekly frame (must contain `hl`)."""
    src = U1_CTREND if spec.get("shortable") else BASE_CTREND
    col = spec.get("signal_col", "ctrend")
    df = load_panel(src, col)

    if spec.get("ewma_halflife", 0):
        df = ewma_signal(df, col="sig", halflife_weeks=spec["ewma_halflife"])

    res = sort_portfolios(
        df, "sig",
        buffer_width=spec.get("buffer_width", 0.0),
        max_name_weight=spec.get("max_name_weight", 1.0),
        adv_col="dvol" if spec.get("book_size_usd") else None,
        book_size_usd=spec.get("book_size_usd"),
        participation=spec.get("participation"),
    )
    w = res.weekly.copy()
    if w.empty:
        return w

    if spec.get("vol_target"):
        w = vol_target(w, ret_col="hl", target_ann_vol=spec["vol_target"],
                       lookback_weeks=spec.get("vol_lookback", 26),
                       max_leverage=spec.get("max_leverage", 2.0))
        w["hl"] = w["hl_vt"]
    if spec.get("hedge"):
        w["mkt"] = w["week"].map(mkt)
        w = beta_hedge(w, ret_col="hl", bench_col="mkt",
                       window_weeks=spec.get("beta_window", 26),
                       funding=fund, credit_funding=spec.get("credit_funding", True))
        w["hl"] = w["hl_hedged"]
    return w


def series_on(w: pd.DataFrame, lo: int, hi: int) -> pd.Series:
    if w.empty:
        return pd.Series(dtype=float)
    s = w[(w["week"] >= lo) & (w["week"] <= hi)]
    return s.set_index("week")["hl"]


def sharpe_net(w: pd.DataFrame, lo: int, hi: int, tc: float = 0.0055) -> float:
    if w.empty:
        return -np.inf
    s = w[(w["week"] >= lo) & (w["week"] <= hi)]
    if len(s) < 20:
        return -np.inf
    net = s["hl"] - tc * s.get("turnover", 0.0)
    sd = net.std(ddof=1)
    return float(net.mean() / sd * np.sqrt(52)) if sd > 0 else -np.inf


def freeze(params: dict, grid_points: int, mde: dict, path: Path = FROZEN) -> None:
    body = {
        "tuning_window": {"start": TUNE_START, "end": TUNE_END},
        "eval_window": {"start": EVAL_START, "end": EVAL_END},
        "selection_criterion": "net_sharpe_55bps_on_tuning_window",
        "n_grid_points_searched": grid_points,
        "params": params,
        "mde_paired_pct_wk": mde,
    }
    body["integrity_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2))
    log.info("frozen -> %s", path)


def load_frozen(path: Path = FROZEN) -> dict:
    body = json.loads(Path(path).read_text())
    claimed = body.pop("integrity_sha256")
    actual = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    if claimed != actual:
        raise RuntimeError(
            f"{path} was edited after freezing (hash mismatch) — the evaluation "
            "window is no longer held out"
        )
    body["integrity_sha256"] = claimed
    return body
