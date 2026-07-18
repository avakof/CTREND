"""Partition poisoning — the physical proof that ``asof`` never opens the future.

Overwriting every partition after week *t* with non-parquet bytes turns "did the
query read a future file?" into an observable fact rather than an assertion about
instrumentation: a query that *succeeds* over a poisoned future provably never
opened those files, while a full scan raises.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["poison_partitions_after"]

_GARBAGE = b"NOT A PARQUET FILE -- if you can read this, asof opened the future\n" * 64


def poison_partitions_after(root: str | Path, week: int) -> list[Path]:
    """Corrupt every ``panel/week_id=NNNN/part.parquet`` for weeks > ``week``."""
    root = Path(root)
    ruined: list[Path] = []
    for pdir in sorted((root / "panel").glob("week_id=*")):
        wid = int(pdir.name.split("=")[1])
        if wid > week:
            for f in pdir.glob("*.parquet"):
                f.write_bytes(_GARBAGE)
                ruined.append(f)
    if not ruined:
        raise RuntimeError(f"no partitions after week {week} to poison")
    return ruined
