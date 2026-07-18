"""Test-suite bootstrap.

Bit-identity is an *environment* property, not only a code property. BLAS
thread counts change the association order of float reductions, so the thread
caps below are set **before numpy is imported anywhere** — this file is imported
by pytest ahead of any test module. Pair this with the pinned toolchain in
`.python-version` / `uv.lock`.
"""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `fixtures` importable

from ctrend.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def replication_cfg():
    return load_config(Path(__file__).resolve().parents[1] / "configs" / "replication.yaml")


@pytest.fixture(scope="session")
def live_cfg():
    return load_config(Path(__file__).resolve().parents[1] / "configs" / "live.yaml")
