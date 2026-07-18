PY := .venv/bin/python
CONFIG ?= configs/replication.yaml

.PHONY: all ingest indicators signal backtest validate test setup clean

## Reproduce Track A end-to-end from a clean checkout
all: ingest indicators signal backtest validate

setup:
	uv venv --python 3.12
	uv pip install -e .

## M1 — download Track A, build point-in-time universe -> parquet/DuckDB
ingest:
	$(PY) -m ctrend.ingest --config $(CONFIG)

## M2 — compute the 28 technical indicators
indicators:
	$(PY) -m ctrend.indicators --config $(CONFIG)

## M3 — CS-C-ENet walk-forward CTREND signal
signal:
	$(PY) -m ctrend.signal --config $(CONFIG)

## M4 — quintile sorts, turnover, costs
backtest:
	$(PY) -m ctrend.portfolio --config $(CONFIG)

## M5 — acceptance bands vs SPEC.md §7 -> validation_report.md
validate:
	$(PY) -m ctrend.evaluation --config $(CONFIG)

## Invariant I4 — must be green before any milestone is declared done
test:
	$(PY) -m pytest

clean:
	rm -rf .pytest_cache **/__pycache__
