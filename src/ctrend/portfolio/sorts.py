"""Quintile sorts, GKX turnover and transaction costs (SPEC §4.4, M4).

Sort mechanics follow `fSingleSortMulti.m`: MATLAB `quantile(...,'exact')`
breakpoints, a week voided below `iMinNumCS = 25` valid coins or `iMinNumAssets = 5`
per portfolio, the lowest bucket closed on both sides and the rest left-open, and
value weights on **lagged** market cap.

Turnover is Gu-Kelly-Xiu (2020) eq. (14) as the paper states it: per leg, half the
sum of absolute weight changes against the *drifted* prior weights, then the H-L
figure is the **average** of the two legs (`fSingleSortMulti.m:403-410` sums them and
`b14:168` halves the result). The drift term matters -- comparing raw `w_t` to
`w_{t-1}` instead would count price movement as trading and overstate turnover.

Transaction costs use the **undrifted** weight change (`eq. 15`), which is a
different quantity from the reported turnover. The authors do the same, and the
breakeven figure divides by yet a third variant (`fSingleSortMulti.m:329`, raw
`sum|dw|`, unhalved). These are deliberately kept distinct.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_CS = 25
MIN_ASSETS = 5
N_Q = 5

__all__ = ["matlab_quantile", "assign_quintiles", "sort_portfolios", "SortResult"]


def matlab_quantile(x: np.ndarray, qs: np.ndarray) -> np.ndarray:
    """MATLAB `quantile(..., 'Method','exact')` — (i-0.5)/n plotting positions."""
    x = np.sort(np.asarray(x, dtype="float64"))
    n = len(x)
    if n == 0:
        return np.full(len(qs), np.nan)
    pos = (np.arange(1, n + 1) - 0.5) / n
    return np.interp(qs, pos, x, left=x[0], right=x[-1])


def assign_quintiles(v: np.ndarray, n_q: int = N_Q) -> np.ndarray:
    cuts = matlab_quantile(v, np.linspace(0, 1, n_q + 1))
    return np.searchsorted(cuts[1:-1], v, side="left")


class SortResult:
    """Weekly portfolio returns, turnover and net-of-cost returns."""

    def __init__(self, weekly: pd.DataFrame, weights: dict[int, dict[int, pd.Series]]):
        self.weekly = weekly
        self.weights = weights

    @property
    def hl(self) -> pd.Series:
        return self.weekly.set_index("week")["hl"]


def _leg_turnover(prev: pd.Series | None, cur: pd.Series, ret: pd.Series) -> float:
    """GKX per-leg turnover: 0.5 * sum |w_t - drifted(w_{t-1})|."""
    if prev is None:
        return float(cur.abs().sum())  # opening the book is full turnover
    idx = prev.index.union(cur.index)
    p = prev.reindex(idx).fillna(0.0)
    c = cur.reindex(idx).fillna(0.0)
    r = ret.reindex(idx).fillna(0.0)
    drifted = p * (1.0 + r)
    denom = drifted.sum()
    if denom <= 0:
        return float((c - p).abs().sum() * 0.5)
    return float(0.5 * (c - drifted / denom).abs().sum())


def cap_weights(w: pd.Series, *, max_name_weight: float = 1.0,
                adv: pd.Series | None = None, book_size_usd: float | None = None,
                participation: float | None = None,
                residual: str = "cash") -> tuple[pd.Series, float]:
    """Cap weights by name and/or tradable size, water-filling the excess (U6).

    Two caps, both optional and both identity at their defaults:

    * ``max_name_weight`` — concentration. Needed because the live-perp universe has
      an effective N of ~2: BTC is 51-68% of its market cap, so an uncapped
      value-weighted quintile *is* BTC and the sort tests nothing.
    * ``participation x ADV / book_size`` — capacity.

    ``residual="cash"`` is the default and the honest one: the uninvested fraction is
    held at zero return and reported. Renormalising to sum 1 would push the excess
    into other names, i.e. assume away the very constraint being measured.
    """
    w = w.astype(float).copy()
    cap = pd.Series(max_name_weight, index=w.index, dtype=float)
    if adv is not None and book_size_usd and participation:
        cap = np.minimum(cap, (participation * adv.reindex(w.index).fillna(0.0))
                         / book_size_usd)
    if (w <= cap + 1e-15).all():
        return w, 0.0

    # Water-fill: cap the binding names, redistribute pro-rata among the rest,
    # repeat until nothing new binds.
    for _ in range(64):
        over = w > cap + 1e-15
        if not over.any():
            break
        excess = float((w[over] - cap[over]).sum())
        w[over] = cap[over]
        free = ~over & (w < cap - 1e-15)
        if not free.any() or excess <= 0:
            break
        headroom = (cap[free] - w[free])
        share = headroom / headroom.sum()
        w[free] = w[free] + np.minimum(excess * share, headroom)
    total = float(w.sum())
    uninvested = max(0.0, 1.0 - total)
    if residual == "renormalize" and total > 0:
        w = w / total
        uninvested = 0.0
    return w, uninvested


def apply_buffer(pct: np.ndarray, coins: pd.Index, prev_top: set | None,
                 prev_bot: set | None, n_q: int, width: float) -> np.ndarray:
    """Hysteresis on extreme-bucket membership (U3 lever b).

    Enter at the nominal breakpoint; leave only once `width` percentile units beyond
    it. Cuts turnover by not trading names that jitter across a boundary.
    ``width == 0.0`` is the identity and is asserted as bit-exact in the tests.
    """
    q = np.searchsorted(np.linspace(0, 1, n_q + 1)[1:-1], pct, side="left")
    if width <= 0 or prev_top is None:
        return q
    top_in, bot_in = 1.0 - 1.0 / n_q, 1.0 / n_q
    for i, c in enumerate(coins):
        if c in prev_top and pct[i] >= top_in - width:
            q[i] = n_q - 1
        elif c in prev_bot and pct[i] <= bot_in + width:
            q[i] = 0
    return q


def sort_portfolios(df: pd.DataFrame, signal: str, *, n_q: int = N_Q,
                    tc_long: float = 0.0030, tc_short: float = 0.0040,
                    buffer_width: float = 0.0, max_name_weight: float = 1.0,
                    adv_col: str | None = None, book_size_usd: float | None = None,
                    participation: float | None = None,
                    residual: str = "cash") -> SortResult:
    """Value-weighted quintile sorts on ``signal``.

    ``df`` needs columns: ``week``, ``coin_id``, ``signal``, ``fwd`` (the realised
    return the signal predicts) and ``mcap`` (the **lagged** market cap used for
    weighting, i.e. what is known when the portfolio is formed).
    """
    rows: list[dict] = []
    weights: dict[int, dict[int, pd.Series]] = {}
    prev_w: dict[int, pd.Series] = {}
    prev_top: set | None = None
    prev_bot: set | None = None
    prev_ret: dict[int, pd.Series] = {}

    for wk, g in df.groupby("week", sort=True):
        g = g.dropna(subset=[signal, "fwd", "mcap"])
        g = g[g["mcap"] > 0]
        if len(g) < MIN_CS:
            continue
        v = g[signal].to_numpy()
        pct = (pd.Series(v).rank(method="average").to_numpy() - 1) / max(len(v) - 1, 1)
        q = apply_buffer(pct, pd.Index(g["coin_id"]), prev_top, prev_bot, n_q,
                         buffer_width) if buffer_width > 0 else assign_quintiles(v, n_q)
        g = g.assign(q=q)
        if any(len(g[g.q == k]) < MIN_ASSETS for k in (0, n_q - 1)):
            continue

        rec: dict = {"week": int(wk), "n": len(g)}
        cur_w: dict[int, pd.Series] = {}
        uninv: dict[int, float] = {}
        for k in range(n_q):
            s = g[g.q == k]
            w = (s["mcap"] / s["mcap"].sum()).set_axis(s["coin_id"])
            if max_name_weight < 1.0 or (adv_col and book_size_usd and participation):
                adv = (s.set_index("coin_id")[adv_col] / 7.0) if adv_col else None
                w, un = cap_weights(w, max_name_weight=max_name_weight, adv=adv,
                                    book_size_usd=book_size_usd,
                                    participation=participation, residual=residual)
                uninv[k] = un
            cur_w[k] = w
            rec[f"q{k + 1}"] = float((w * s.set_index("coin_id")["fwd"]).sum())
        rec["hl"] = rec[f"q{n_q}"] - rec["q1"]
        # Concentration diagnostics: with an effective N near 2, a value-weighted
        # quintile can BE one coin, and the sort would test nothing.
        wl, ws = cur_w[n_q - 1], cur_w[0]
        rec["top1_long"] = float(wl.max()) if len(wl) else np.nan
        rec["eff_n_long"] = float(1.0 / (wl**2).sum()) if len(wl) else np.nan
        rec["top1_short"] = float(ws.max()) if len(ws) else np.nan
        rec["eff_n_short"] = float(1.0 / (ws**2).sum()) if len(ws) else np.nan
        rec["uninvested_long"] = uninv.get(n_q - 1, 0.0)
        rec["uninvested_short"] = uninv.get(0, 0.0)

        # Turnover on the two traded legs, then averaged (b14:168).
        to_l = _leg_turnover(prev_w.get(n_q - 1), cur_w[n_q - 1],
                             prev_ret.get(n_q - 1, pd.Series(dtype=float)))
        to_s = _leg_turnover(prev_w.get(0), cur_w[0],
                             prev_ret.get(0, pd.Series(dtype=float)))
        rec["to_long"], rec["to_short"] = to_l, to_s
        rec["turnover"] = 0.5 * (to_l + to_s)

        # Costs use the UNDRIFTED weight change (eq. 15), a different quantity.
        def raw_change(prev: pd.Series | None, cur: pd.Series) -> float:
            if prev is None:
                return float(cur.abs().sum())
            idx = prev.index.union(cur.index)
            return float((cur.reindex(idx).fillna(0.0)
                          - prev.reindex(idx).fillna(0.0)).abs().sum())

        cost = (tc_long * raw_change(prev_w.get(n_q - 1), cur_w[n_q - 1])
                + tc_short * raw_change(prev_w.get(0), cur_w[0]))
        rec["cost"] = cost
        rec["hl_net"] = rec["hl"] - cost
        rows.append(rec)

        weights[int(wk)] = cur_w
        prev_top = set(cur_w[n_q - 1].index)
        prev_bot = set(cur_w[0].index)
        prev_w = cur_w
        prev_ret = {k: g[g.q == k].set_index("coin_id")["fwd"] for k in range(n_q)}

    return SortResult(pd.DataFrame(rows), weights)
