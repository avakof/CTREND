"""Tune on 2022-23, freeze, evaluate ONCE on 2024-26, report all configurations."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ctrend.experiments.harness import (build_series, freeze, funding_series,
                                        load_frozen, market_series, series_on,
                                        sharpe_net)
from ctrend.experiments.stats import report_table
from ctrend.experiments.windows import EVAL_END, EVAL_START, TUNE_END, TUNE_START

log = logging.getLogger("experiment")
NAME_CAP = 0.10          # pre-registered, NOT tuned (effective N ~2 in the perp universe)
BOOK = 50_000_000.0      # pre-registered capacity point
PARTICIPATION = 0.01     # standard desk assumption, NOT tuned


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    mkt, fund = market_series(), funding_series()
    cache: dict[str, pd.DataFrame] = {}

    def series(spec: dict, key: str) -> pd.DataFrame:
        if key not in cache:
            cache[key] = build_series(spec, mkt, fund)
        return cache[key]

    # ---------------- tuning: 2022-23 only ----------------
    log.info("TUNING on %d-%d (parameters chosen here and nowhere else)", TUNE_START, TUNE_END)
    base_tune = series({}, "base")
    tgt = float(series_on(base_tune, TUNE_START, TUNE_END).std(ddof=1) * np.sqrt(52))
    log.info("vol target pinned to the tuning-window baseline vol: %.1f%% ann", 100 * tgt)

    searched = 0
    best: dict = {}

    cands = [("vol_lookback", L, {"vol_target": tgt, "vol_lookback": L}) for L in (13, 26, 52)]
    scores = []
    for _, L, spec in cands:
        searched += 1
        w = series(spec, f"vt{L}")
        scores.append((sharpe_net(w, TUNE_START, TUNE_END), L))
    best["vol_lookback"] = max(scores)[1]

    scores = []
    for bw in (0.05, 0.10, 0.15):
        searched += 1
        w = series({"buffer_width": bw}, f"buf{bw}")
        scores.append((sharpe_net(w, TUNE_START, TUNE_END), ("buffer", bw)))
    for hl in (1, 2, 4):
        searched += 1
        w = series({"ewma_halflife": hl}, f"ewma{hl}")
        scores.append((sharpe_net(w, TUNE_START, TUNE_END), ("ewma", hl)))
    best["turnover_lever"] = max(scores)[1]

    scores = []
    for n in (2, 3, 4):
        searched += 1
        w = series({"signal_col": f"ctrend_n{n}"}, f"stab{n}")
        scores.append((sharpe_net(w, TUNE_START, TUNE_END), n))
    best["stability_n"] = max(scores)[1]

    scores = []
    for bwin in (13, 26, 52):
        searched += 1
        w = series({"hedge": True, "beta_window": bwin}, f"hg{bwin}")
        scores.append((sharpe_net(w, TUNE_START, TUNE_END), bwin))
    best["beta_window"] = max(scores)[1]
    best["vol_target"] = tgt
    log.info("selected on the tuning window: %s  (%d grid points searched)", best, searched)

    # ---------------- configurations ----------------
    lever, lval = best["turnover_lever"]
    turn = {"buffer_width": lval} if lever == "buffer" else {"ewma_halflife": lval}
    vt = {"vol_target": tgt, "vol_lookback": best["vol_lookback"]}
    stab = {"signal_col": f"ctrend_n{best['stability_n']}"}
    hg = {"hedge": True, "beta_window": best["beta_window"]}
    cap = {"book_size_usd": BOOK, "participation": PARTICIPATION}
    u1 = {"shortable": True, "max_name_weight": NAME_CAP}

    configs = {
        "C0 baseline": {},
        "C1 shortable+cap": u1,
        "C2 vol-target": vt,
        "C3 turnover": turn,
        "C4 beta-hedge": hg,
        "C5 stability": stab,
        "C6 capacity": cap,
        "C7 C1+C6": {**u1, **cap},
        "C8 stack": {**u1, **turn, **stab, **vt, **cap},
        "C9 stack+hedge": {**u1, **turn, **stab, **vt, **cap, **hg},
    }

    # MDE of the PAIRED difference, measured on the tuning window and frozen BEFORE
    # the evaluation is read. This is what makes a null interpretable.
    base_t = series_on(base_tune, TUNE_START, TUNE_END)
    mde = {}
    for name, spec in configs.items():
        if name == "C0 baseline":
            continue
        w = series(spec, name)
        s = series_on(w, TUNE_START, TUNE_END)
        common = base_t.index.intersection(s.index)
        if len(common) < 20:
            continue
        sd = float((s.loc[common] - base_t.loc[common]).std(ddof=1))
        mde[name] = round(100 * (2.576 + 0.842) * sd / np.sqrt(133), 3)
    freeze(best, searched, mde)

    # ---------------- evaluation: ONE pass on 2024-26 ----------------
    frozen = load_frozen()
    log.info("frozen params verified (sha %s...)", frozen["integrity_sha256"][:12])
    log.info("EVALUATING on %d-%d", EVAL_START, EVAL_END)
    ev = {name: series_on(series(spec, name), EVAL_START, EVAL_END)
          for name, spec in configs.items()}
    tune_ev = {name: series_on(series(spec, name), TUNE_START, TUNE_END)
               for name, spec in configs.items()}

    tbl = report_table(ev, baseline="C0 baseline", expected=set(configs))
    tbl["tune_mean_pct"] = [tune_ev[n].mean() * 100 for n in tbl["config"]]
    tbl["mde_pct"] = [frozen["mde_paired_pct_wk"].get(n, np.nan) for n in tbl["config"]]
    Path("reports").mkdir(exist_ok=True)
    tbl.to_csv("reports/upgrades_evaluation.csv", index=False)

    print("\n" + "=" * 104)
    print(f"UPGRADE EXPERIMENT — evaluation window {EVAL_START}-{EVAL_END} "
          f"({len(ev['C0 baseline'])} weeks), held out")
    print(f"parameters fitted on {TUNE_START}-{TUNE_END} only; "
          f"{frozen['n_grid_points_searched']} grid points searched")
    print("PRE-REGISTERED minimum detectable effect (paired, Bonferroni, 80% power):")
    for k, v in frozen["mde_paired_pct_wk"].items():
        print(f"   {k:<20} {v:>6.2f} %/wk")
    print("=" * 104)
    cols = ["config", "n", "mean_pct", "sharpe", "max_dd_pct", "hit_pct",
            "diff_mean_pct", "t_paired", "p_raw", "q_BH", "bonferroni_pass",
            "sr_haircut_M31", "tune_mean_pct"]
    print(tbl[cols].to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    print(f"\nSPA p-value (best config genuinely beats baseline): {tbl.attrs['spa_p']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
