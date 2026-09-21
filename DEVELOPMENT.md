# CTREND — replication + OOS extension of Fieberg et al., JFQA 2025 (60, 3116–3153)
Authoritative spec: SPEC.md. Ambiguity ledger: DECISIONS.md.
This file is context, not enforcement: invariants are enforced by tests.

## Invariants (task fails if violated)
1. No look-ahead: week-t quantities use data <= t only; all access via
   Dataset.asof(week); tests/test_no_lookahead.py must stay green.
2. No silent spec deviations: config flag + DECISIONS.md entry required.
   Never substitute cross-validation for AICc lambda selection.
3. Acceptance bands in SPEC.md are immutable; a failed gate means STOP +
   diagnosis, never parameter search until green.
4. Every module has pytest tests; run `make test` before declaring done.
5. Laptop scale only: pandas/polars + parquet + DuckDB. No services, no Spark.
6. Secrets only via untracked .env.
7. Never emit live orders — order sheets (CSV) only.
8. STOP checkpoints: CP-1 (post data inventory), CP-2 (before any spend or
   credentials), CP-3 (post validation report).

## Paper defaults (configs/replication.yaml)
weekly frequency · M = 52-week rolling estimation · WLS weights = market cap
signals rank-mapped cross-sectionally to [-0.5, +0.5]
ElasticNet l1_ratio=0.5, lambda by corrected AIC (custom grid; no CV)
theta_j > 0 forecast selection; equal-weight the surviving forecasts
value-weighted quintile portfolios, weekly rebalance · mcap >= USD 1M
drop observations with mcap > Bitcoin's · returns truncated at 0.5%/99.5%

## Commands
make ingest | make indicators | make signal | make backtest | make validate | make test

## Workflow
One milestone per session. Re-read the SPEC.md gate before declaring done.
Golden tests and acceptance bands are read-only.
