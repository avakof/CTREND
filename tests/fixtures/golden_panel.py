"""The SPEC §5 golden miniature, materialised as a curated panel.

The installed golden (``tests/golden/test_cenet_golden.py``) imports only numpy,
sklearn and scipy: it never touches ``src/``. It is a *behavioural reference*,
not an integration test, so "the golden is green" says nothing about
``src/ctrend/signal/``. This module reproduces the golden's exact data — the
same seed and, critically, the same RNG **draw order** (Z, then the per-week
noise inside the t-loop, then mcap) — as a real panel, so the production core can
be driven over it through ``Dataset.asof`` and compared.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ctrend.calendar import WeekIndex
from ctrend.data.schema import SIGNAL_COLUMNS

__all__ = ["GOLDEN", "build_golden_panel"]


class _G:
    N, T, J, M = 250, 90, 28, 52
    SEED = 7
    PLANTED = (0, 3, 7, 12, 20)
    LOADINGS = (0.9, 0.7, -0.5, 0.6, 0.4)


GOLDEN = _G


def golden_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reproduce the golden's ``Z``, ``R`` and ``mcap`` exactly."""
    rng = np.random.default_rng(_G.SEED)
    N, T, J = _G.N, _G.T, _G.J
    true_b = np.zeros(J)
    true_b[list(_G.PLANTED)] = _G.LOADINGS
    Z = rng.uniform(-0.5, 0.5, (T, N, J))
    R = np.zeros((T, N))
    for t in range(1, T):
        R[t] = Z[t - 1] @ true_b + rng.normal(0, 3, N)  # draw order is load-bearing
    mcap = rng.lognormal(3, 1, N)
    return Z, R, mcap


def build_golden_panel(root: str | Path) -> tuple[Path, WeekIndex, np.ndarray, np.ndarray]:
    """Write the golden miniature to ``root`` as a curated panel."""
    root = Path(root)
    (root / "panel").mkdir(parents=True, exist_ok=True)
    Z, R, mcap = golden_arrays()
    N, T = _G.N, _G.T

    # Weights are normalised inside the WLS, so a constant rescale of mcap
    # leaves alpha and beta bit-identical; it only lifts the USD 1M floor.
    mcap_usd = mcap * 1.0e6

    for t in range(T):
        d = pd.DataFrame(
            {
                "coin_id": np.arange(N, dtype="int64"),
                "close": np.full(N, 100.0),
                "dollar_volume": mcap_usd * 0.05,
                "market_cap": mcap_usd,
                "weekly_return": R[t],
                "excess_return": R[t],
            }
        )
        for j, col in enumerate(SIGNAL_COLUMNS):
            d[col] = Z[t, :, j]
        pdir = root / "panel" / f"week_id={t:04d}"
        pdir.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(d, preserve_index=False), pdir / "part.parquet")

    pd.DataFrame(
        {
            "coin_id": np.arange(N, dtype="int64"),
            # deliberately no "BTC": the golden has no dominant coin, so the
            # drop_mcap_above_btc rule must not fire here
            "symbol": [f"G{i:03d}" for i in range(N)],
            "first_seen_week": np.zeros(N, dtype="int32"),
        }
    ).to_parquet(root / "coin_registry.parquet", index=False)

    pd.DataFrame(
        {
            "coin_id": np.array([], dtype="int64"),
            "last_trade_week": np.array([], dtype="int32"),
            "last_price": np.array([], dtype="float64"),
            "reason": np.array([], dtype=object),
        }
    ).to_parquet(root / "delisting_registry.parquet", index=False)

    start = pd.Timestamp("2015-04-05")  # a Sunday
    cal = WeekIndex(start, start + pd.Timedelta(days=7 * (T - 1)), "sunday")
    assert len(cal) == T
    return root, cal, Z, R
