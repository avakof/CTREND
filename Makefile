PY := PYTHONPATH=src .venv/bin/python
CONFIG ?= configs/replication.yaml

.PHONY: all harvest ingest indicators signal backtest validate gate m6 test setup clean

## Reproduce the pipeline end to end from already-harvested raw data (SPEC §9).
## `harvest` is separate because it hits a third-party API for ~40 minutes and
## should be an explicit choice, not a side effect of `make all`.
all: ingest indicators signal backtest validate

setup:
	uv venv --python 3.12
	uv pip install -e .

## ---------------------------------------------------------------------------
## Raw acquisition (explicit; see DECISIONS.md Part 3 on CMC terms)
## ---------------------------------------------------------------------------
harvest:
	$(PY) -m ctrend.ingest.cmc_snapshots --start 2013-04-28 --end 2026-07-18
	$(PY) -m ctrend.ingest.cmc_ohlc --delay 0.5 --workers 3
	$(PY) -m ctrend.ingest.gandal_ohlc

## M1 — curate the daily snapshots into the weekly panel + universe registry
ingest:
	$(PY) -m ctrend.ingest.curate --config $(CONFIG)

## M2 — the 28 technical indicators, weekly-resampled and rank-mapped
indicators:
	$(PY) -m ctrend.indicators.pipeline

## M3 — curated layout for Dataset, then the CS-C-ENet walk-forward
signal:
	$(PY) -m ctrend.ingest.to_curated
	$(PY) -m ctrend.signal.run_m3 --config $(CONFIG)

## M4 — pipeline canary FIRST (SPEC §6: validates the machinery independently
## of the novel signal), then the factor reconstruction
backtest:
	$(PY) -m ctrend.portfolio.canary
	$(PY) -m ctrend.evaluation.factors

## M5 — the immutable SPEC §7 acceptance gate + comparison to the shipped factor
validate: gate
	$(PY) -m ctrend.evaluation.validate_ctrend

gate:
	$(PY) -m ctrend.evaluation.gate

## M6 — out-of-sample decay and the implementable variants
m6:
	$(PY) -m ctrend.costs.feasibility_mask
	$(PY) -m ctrend.evaluation.m6_variants

## Invariant I4 — must be green before any milestone is declared done
test:
	.venv/bin/python -m pytest

clean:
	rm -rf .pytest_cache **/__pycache__
