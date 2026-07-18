"""Deterministic synthetic panel — the M0 fixture.

Generates daily OHLCV + market cap + dollar volume for several coins over >= 120
weeks, aggregates it to Sunday-close weeks (A3), rank-maps 28 synthetic
indicators to [-0.5, +0.5] (SPEC §4.2), and writes the curated hive-partitioned
layout that :class:`ctrend.data.store.DuckDBPanelStore` reads.

The panel deliberately contains:
  * one coin delisted mid-sample (week ~70) and never resurrected;
  * one coin that lists late (week ~35);
  * one coin that dips below the USD 1M market-cap floor and recovers;
  * one week with a degenerate (all-tied) signal column, which exercises the
    ``np.maximum(var, 1e-12)`` guard in SPEC §4.3 step 1;
  * planted structure on indicators {0, 3, 7, 12, 20} so the ENet selection is
    non-empty and CTREND is not vacuously NaN.

``noise_after`` is the look-ahead instrument: it rewrites **every** value
strictly after that week at 100x scale with a different drift, plants phantom
coins that first appear only afterwards, and kills live coins afterwards. It
deliberately preserves the week grid, the identity and order of coins first seen
at or before the split, and does **not** resurrect the dead coin — a resurrection
would change the pre-split universe for a legitimate reason and produce a
confusing red.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import rankdata

from ctrend import J_INDICATORS
from ctrend.calendar import WeekIndex
from ctrend.data.schema import SIGNAL_COLUMNS

__all__ = ["PanelSpec", "build_panel", "FIXTURE_START"]

FIXTURE_START = pd.Timestamp("2015-04-01")

#: planted loadings, mirroring the SPEC §5 golden's mixed-sign design
TRUE_B_IDX = (0, 3, 7, 12, 20)
TRUE_B_VAL = (0.9, 0.7, -0.5, 0.6, 0.4)


@dataclass(frozen=True)
class PanelSpec:
    root: Path
    n_weeks: int
    n_coins: int
    calendar: WeekIndex
    btc_id: int
    dead_coin: int
    dead_week: int
    late_coin: int
    late_week: int
    dipping_coin: int
    degenerate_week: int
    noise_after: int | None


def build_panel(
    root: str | Path,
    *,
    seed: int = 20260718,
    n_weeks: int = 130,
    n_coins: int = 40,
    noise_after: int | None = None,
    noise_seed: int | None = None,
) -> PanelSpec:
    """Write a curated fixture panel under ``root`` and describe it."""
    root = Path(root)
    (root / "panel").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    T, N = n_weeks, n_coins
    btc_id, dead_coin, late_coin, dipping_coin = 0, 7, 11, 19
    dead_week, late_week, degenerate_week = 70, 35, 44

    # ---- weekly latent signals ------------------------------------------ #
    # Persistent raw indicator values; rank-mapped per week further down.
    raw = np.zeros((T, N, J_INDICATORS))
    raw[0] = rng.normal(size=(N, J_INDICATORS))
    for t in range(1, T):
        raw[t] = 0.7 * raw[t - 1] + rng.normal(size=(N, J_INDICATORS))
    # degenerate column: indicator 27 is identical across coins in one week,
    # so its rank map is all-ties -> zero cross-sectional variance.
    raw[degenerate_week, :, J_INDICATORS - 1] = 1.234

    # ---- lifetimes ------------------------------------------------------- #
    first_seen = np.zeros(N, dtype=int)
    first_seen[late_coin] = late_week
    last_week = np.full(N, T - 1, dtype=int)
    last_week[dead_coin] = dead_week

    alive = np.zeros((T, N), dtype=bool)
    for c in range(N):
        alive[first_seen[c] : last_week[c] + 1, c] = True

    # ---- rank map to [-0.5, +0.5] (SPEC §4.2), cross-sectionally per week - #
    Z = np.full((T, N, J_INDICATORS), np.nan)
    for t in range(T):
        idx = np.flatnonzero(alive[t])
        if idx.size == 0:
            continue
        block = raw[t][idx]
        r = np.apply_along_axis(lambda col: rankdata(col, method="average"), 0, block)
        Z[t][idx] = (r - 0.5) / idx.size - 0.5

    # ---- returns: r_t depends on z_{t-1} (planted structure) -------------- #
    true_b = np.zeros(J_INDICATORS)
    true_b[list(TRUE_B_IDX)] = TRUE_B_VAL
    R = np.zeros((T, N))
    for t in range(1, T):
        z_prev = np.nan_to_num(Z[t - 1], nan=0.0)
        R[t] = 0.30 * (z_prev @ true_b) + rng.normal(0, 0.10, N)
    R[0] = rng.normal(0, 0.10, N)
    R = np.clip(R, -0.9, 4.0)

    # ---- prices, market cap, volume --------------------------------------- #
    base_price = rng.lognormal(1.5, 1.0, N)
    price = np.zeros((T, N))
    price[0] = base_price
    for t in range(1, T):
        price[t] = price[t - 1] * (1.0 + R[t])
    price = np.maximum(price, 1e-8)

    # Sized so that ordinary coins clear the USD 1M floor across the whole
    # sample while BTC dominates, so `drop_mcap_above_btc` never fires by
    # accident. The two filters are exercised deliberately, not incidentally:
    # `dipping_coin` below, and the BTC rule by the post-split corruption.
    supply = rng.lognormal(16.5, 0.8, N)
    supply[btc_id] = np.exp(21.0)  # BTC dominates: nothing exceeds its market cap
    mcap = price * supply
    # one coin dips below the USD 1M floor for ~8 weeks and recovers
    mcap[:, dipping_coin] = np.maximum(mcap[:, dipping_coin], 2.0e6)
    mcap[50:58, dipping_coin] = 4.0e5
    # the delisted coin must be a genuine, eligible member of the universe right
    # up to its death — otherwise the delisting channel is never exercised by
    # the signal and the A4 test asserts nothing.
    mcap[:, dead_coin] = np.maximum(mcap[:, dead_coin], 5.0e6)
    dvol = mcap * rng.uniform(0.01, 0.20, size=(T, N))

    # ---- post-split corruption (the look-ahead instrument) ---------------- #
    phantom_ids: list[int] = []
    if noise_after is not None:
        nrng = np.random.default_rng(noise_seed if noise_seed is not None else 999)
        s = int(noise_after) + 1
        if s < T:
            Z[s:] = nrng.uniform(-0.5, 0.5, (T - s, N, J_INDICATORS))
            R[s:] = 100.0 * nrng.normal(0.5, 1.0, (T - s, N))
            price[s:] = np.maximum(100.0 * nrng.lognormal(2.0, 1.5, (T - s, N)), 1e-8)
            mcap[s:] = 100.0 * nrng.lognormal(16.0, 1.5, (T - s, N))
            mcap[s:, btc_id] = mcap[s:].max() * 10.0
            dvol[s:] = 100.0 * nrng.lognormal(14.0, 1.5, (T - s, N))
            # kill live coins after the split (registry-shaped corruption);
            # never resurrect the already-dead coin.
            for c in (3, 21):
                last_week[c] = min(last_week[c], s + 4)
                alive[s + 5 :, c] = False
            # phantom coins first seen only after the split
            phantom_ids = [N + 1, N + 2]

    # ---- daily bars, aggregated back to Sunday-close weeks (A3) ----------- #
    _anchor = WeekIndex(FIXTURE_START, FIXTURE_START + pd.Timedelta(days=7), "sunday")
    cal = WeekIndex(
        FIXTURE_START, _anchor.first_close + pd.Timedelta(days=7 * (T - 1)), "sunday"
    )
    assert len(cal) == T, (len(cal), T)
    daily = _daily_bars(cal, alive, price, mcap, dvol, rng)
    weekly = _aggregate_weekly(cal, daily)

    # ---- assemble the curated panel --------------------------------------- #
    frames = []
    for t in range(T):
        idx = np.flatnonzero(alive[t])
        if idx.size == 0:
            continue
        wk = weekly[t]
        d = pd.DataFrame(
            {
                "week_id": np.int32(t),
                "coin_id": idx.astype("int64"),
                "close": wk["close"][idx],
                "dollar_volume": wk["dollar_volume"][idx],
                "market_cap": wk["market_cap"][idx],
                "weekly_return": R[t][idx],
                "excess_return": R[t][idx],  # risk_free: 0.0
            }
        )
        zt = np.nan_to_num(Z[t][idx], nan=0.0)
        for j, col in enumerate(SIGNAL_COLUMNS):
            d[col] = zt[:, j]
        frames.append(d)

    if phantom_ids:
        prng = np.random.default_rng(4242)
        for t in range(int(noise_after) + 1, T):
            d = pd.DataFrame(
                {
                    "week_id": np.int32(t),
                    "coin_id": np.array(phantom_ids, dtype="int64"),
                    "close": prng.lognormal(3, 1, len(phantom_ids)),
                    "dollar_volume": prng.lognormal(16, 1, len(phantom_ids)),
                    "market_cap": prng.lognormal(17, 1, len(phantom_ids)),
                    "weekly_return": prng.normal(0, 5, len(phantom_ids)),
                    "excess_return": prng.normal(0, 5, len(phantom_ids)),
                }
            )
            for col in SIGNAL_COLUMNS:
                d[col] = prng.uniform(-0.5, 0.5, len(phantom_ids))
            frames.append(d)

    panel = pd.concat(frames, ignore_index=True).sort_values(["week_id", "coin_id"])

    for wid, chunk in panel.groupby("week_id", sort=True):
        pdir = root / "panel" / f"week_id={int(wid):04d}"
        pdir.mkdir(parents=True, exist_ok=True)
        tbl = pa.Table.from_pandas(
            chunk.drop(columns=["week_id"]).reset_index(drop=True), preserve_index=False
        )
        pq.write_table(tbl, pdir / "part.parquet")

    # ---- registries -------------------------------------------------------- #
    reg = pd.DataFrame(
        {
            "coin_id": np.arange(N, dtype="int64"),
            "symbol": ["BTC"] + [f"C{i:03d}" for i in range(1, N)],
            "first_seen_week": first_seen.astype("int32"),
        }
    )
    if phantom_ids:
        reg = pd.concat(
            [
                reg,
                pd.DataFrame(
                    {
                        "coin_id": np.array(phantom_ids, dtype="int64"),
                        "symbol": [f"PHANTOM{i}" for i in phantom_ids],
                        "first_seen_week": np.int32(int(noise_after) + 1),
                    }
                ),
            ],
            ignore_index=True,
        )
    reg.to_parquet(root / "coin_registry.parquet", index=False)

    dead = [(dead_coin, dead_week, float(price[dead_week, dead_coin]), "delisted")]
    if noise_after is not None:
        for c in (3, 21):
            if last_week[c] < T - 1:
                dead.append((c, int(last_week[c]), float(price[last_week[c], c]), "dead"))
    pd.DataFrame(
        dead, columns=["coin_id", "last_trade_week", "last_price", "reason"]
    ).astype({"coin_id": "int64", "last_trade_week": "int32"}).to_parquet(
        root / "delisting_registry.parquet", index=False
    )

    (root / "_provenance.json").write_text(
        f'{{"generator": "tests.fixtures.synthetic", "seed": {seed}, '
        f'"n_weeks": {T}, "n_coins": {N}, "noise_after": {noise_after}}}'
    )

    return PanelSpec(
        root=root,
        n_weeks=T,
        n_coins=N,
        calendar=cal,
        btc_id=btc_id,
        dead_coin=dead_coin,
        dead_week=dead_week,
        late_coin=late_coin,
        late_week=late_week,
        dipping_coin=dipping_coin,
        degenerate_week=degenerate_week,
        noise_after=noise_after,
    )


# --------------------------------------------------------------------------- #
# daily <-> weekly
# --------------------------------------------------------------------------- #
def _daily_bars(cal: WeekIndex, alive, price, mcap, dvol, rng) -> pd.DataFrame:
    """Expand weekly closes into seven daily OHLCV bars per coin-week.

    The last daily bar of a week carries the weekly close exactly, so the
    Sunday-close aggregation (A3) is lossless for `close`.
    """
    T, N = price.shape
    rows = []
    for t in range(T):
        idx = np.flatnonzero(alive[t])
        if idx.size == 0:
            continue
        lo, _ = cal.span(t)
        prev = price[t - 1][idx] if t else price[t][idx]
        for d in range(7):
            frac = (d + 1) / 7.0
            close_d = prev * (price[t][idx] / prev) ** frac
            jitter = rng.uniform(0.995, 1.005, idx.size) if d < 6 else np.ones(idx.size)
            close_d = close_d * jitter
            rows.append(
                pd.DataFrame(
                    {
                        "date": lo + pd.Timedelta(days=d),
                        "coin_id": idx.astype("int64"),
                        "open": close_d * 0.998,
                        "high": close_d * 1.01,
                        "low": close_d * 0.99,
                        "close": close_d,
                        "volume": dvol[t][idx] / 7.0,
                        "market_cap": mcap[t][idx],
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


def _aggregate_weekly(cal: WeekIndex, daily: pd.DataFrame) -> dict[int, dict[str, np.ndarray]]:
    """Aggregate daily bars to Sunday-close weeks (A3)."""
    d = daily.copy()
    d["week_id"] = [cal.of(ts) for ts in d["date"]]
    n_coins = int(d["coin_id"].max()) + 1
    out: dict[int, dict[str, np.ndarray]] = {}
    for wid, chunk in d.groupby("week_id", sort=True):
        last = chunk.sort_values("date").groupby("coin_id").last()
        agg = chunk.groupby("coin_id").agg(dollar_volume=("volume", "sum"))
        close = np.zeros(n_coins)
        mcap = np.zeros(n_coins)
        dvol = np.zeros(n_coins)
        ids = last.index.to_numpy()
        close[ids] = last["close"].to_numpy()
        mcap[ids] = last["market_cap"].to_numpy()
        dvol[ids] = agg["dollar_volume"].reindex(last.index).to_numpy()
        out[int(wid)] = {"close": close, "market_cap": mcap, "dollar_volume": dvol}
    return out
