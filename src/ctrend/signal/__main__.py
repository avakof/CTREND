"""``python -m ctrend.signal --config configs/replication.yaml`` (Makefile: make signal)."""

from __future__ import annotations

import argparse
from pathlib import Path

from ctrend.config import load_config
from ctrend.data.dataset import Dataset
from ctrend.signal.engine import ctrend_frame


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ctrend.signal", description="CS-C-ENet walk-forward (SPEC §4.3)")
    p.add_argument("--config", required=True)
    p.add_argument("--curated", default="data/curated")
    p.add_argument("--out", default="data/curated/ctrend.parquet")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    root = Path(args.curated)
    if not (root / "panel").exists():
        raise SystemExit(
            f"no curated panel at {root}/panel — run `make ingest` first (M1). "
            "M0 ships the signal core and its fixtures only."
        )
    ds = Dataset.open(root, cfg)
    frame = ctrend_frame(ds, cfg)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out, index=False)
    print(f"CTREND rows={len(frame)} weeks={frame['target_week'].nunique()} -> {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
