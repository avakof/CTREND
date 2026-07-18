"""Typed, frozen configuration loader (configs/replication.yaml, configs/live.yaml).

Every key in the YAML must map onto a declared dataclass field: unknown keys are
a hard error, not a warning. That is what makes invariant I2 ("no silent spec
deviations") mechanically enforceable — a flag cannot appear in a config without
a corresponding field here and a DECISIONS.md row.

``Config.hash`` is a content hash of the raw mapping. It is carried into every
``SliceProvenance`` so that a CTREND value can always be traced to the exact
configuration that produced it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import MISSING, dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

__all__ = ["Config", "load_config", "ConfigError"]


class ConfigError(ValueError):
    """Raised for unknown, missing or ill-typed configuration keys."""


# --------------------------------------------------------------------------- #
# Leaf sections
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SampleConfig:
    start: _dt.date
    end: _dt.date | None
    frequency: str


@dataclass(frozen=True, slots=True)
class UniverseConfig:
    min_market_cap_usd: float
    drop_mcap_above_btc: bool
    require: tuple[str, ...]
    include_delisted: bool
    delisting_policy: str  # A4


@dataclass(frozen=True, slots=True)
class ReturnsConfig:
    truncate_lower_pct: float
    truncate_upper_pct: float
    truncation_mode: str  # A5 — "full_sample" | "expanding"
    truncation_scope: str  # "pooled" | "per_week"
    risk_free: float


@dataclass(frozen=True, slots=True)
class IndicatorsConfig:
    macd_denominator: str  # A1
    chaikin_window: int  # A2
    rank_map_range: tuple[float, float]

    @property
    def n(self) -> int:
        """J = 28, fixed by SPEC §4.2; not a tunable."""
        from ctrend import J_INDICATORS

        return J_INDICATORS


@dataclass(frozen=True, slots=True)
class LambdaGridConfig:
    n: int
    log_low: float
    log_high: float


@dataclass(frozen=True, slots=True)
class ElasticNetConfig:
    l1_ratio: float
    lambda_grid: LambdaGridConfig
    selection: str  # must be "aicc" — I2 forbids cross-validation
    max_iter: int


@dataclass(frozen=True, slots=True)
class SignalConfig:
    estimation_window_weeks: int  # M
    wls_weights: str
    elasticnet: ElasticNetConfig
    forecast_selection: str
    combine: str
    training_window: str
    min_pool_weeks: int
    wls_weight_date: str
    wls_weights_normalize: bool
    demean_returns: str
    forecast_alignment: str
    var_floor: float
    min_cross_section: int
    nan_policy: str
    empty_selection: str


@dataclass(frozen=True, slots=True)
class HedgeConfig:
    enabled: bool
    instruments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    n_quantiles: int
    weighting: str
    holding_period_weeks: int
    diagnostic_holding_periods: tuple[int, ...]
    rebalance_weekday: str  # A3 — defines the week boundary Dataset.asof resolves against
    implementation_lag_days: int
    long_only: bool
    liquidity_screen: str


@dataclass(frozen=True, slots=True)
class CostsConfig:
    schemes_bps: tuple[tuple[int, int], ...]
    report_breakeven: bool
    feasibility_mask: bool  # A4
    funding: bool
    hedge: HedgeConfig | None = None


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    newey_west_lags: str
    annualization_factor: int
    factor_models: tuple[str, ...]
    reconstruct_factors: bool
    factor_correlation_gate: float
    decay_split_date: _dt.date | None = None
    rolling_sharpe_window_weeks: int | None = None


@dataclass(frozen=True, slots=True)
class Config:
    mode: str  # "replication" | "live"
    sample: SampleConfig
    universe: UniverseConfig
    returns: ReturnsConfig
    indicators: IndicatorsConfig
    signal: SignalConfig
    portfolio: PortfolioConfig
    costs: CostsConfig
    evaluation: EvaluationConfig
    hash: str = ""
    source_path: str = ""

    def __post_init__(self) -> None:
        if self.mode not in ("replication", "live"):
            raise ConfigError(f"mode must be replication|live, got {self.mode!r}")
        if self.signal.elasticnet.selection != "aicc":
            # Invariant I2: cross-validation is prohibited for lambda selection.
            raise ConfigError(
                "signal.elasticnet.selection must be 'aicc' (I2: cross-validation "
                f"is prohibited); got {self.signal.elasticnet.selection!r}"
            )
        if self.returns.truncation_mode not in ("full_sample", "expanding"):
            raise ConfigError(f"unknown truncation_mode {self.returns.truncation_mode!r}")


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
_TUPLE_OF: dict[type, Any] = {}


def _coerce(value: Any, annotation: Any, path: str) -> Any:
    """Coerce a YAML scalar/sequence into the declared field type."""
    ann = annotation
    optional = False
    if isinstance(ann, str):  # postponed annotations
        optional = "None" in ann
        ann = ann.split("|")[0].strip()
    if value is None:
        if optional:
            return None
        raise ConfigError(f"{path}: null not permitted")

    if ann in ("int",):
        return int(value)
    if ann in ("float",):
        return float(value)
    if ann in ("bool",):
        if not isinstance(value, bool):
            raise ConfigError(f"{path}: expected bool, got {value!r}")
        return value
    if ann in ("str",):
        return str(value)
    if ann.startswith("_dt.date") or ann == "date":
        if isinstance(value, _dt.datetime):
            return value.date()
        if isinstance(value, _dt.date):
            return value
        return pd.Timestamp(value).date()
    if ann.startswith("tuple"):
        if not isinstance(value, (list, tuple)):
            raise ConfigError(f"{path}: expected a sequence, got {value!r}")
        return tuple(tuple(v) if isinstance(v, list) else v for v in value)
    # nested dataclass
    cls = _SECTION_TYPES.get(ann)
    if cls is None:
        raise ConfigError(f"{path}: unsupported annotation {annotation!r}")
    return _build(cls, value, path)


def _build(cls: type, mapping: Any, path: str) -> Any:
    if not isinstance(mapping, Mapping):
        raise ConfigError(f"{path}: expected a mapping, got {type(mapping).__name__}")
    declared = {f.name: f for f in fields(cls)}
    unknown = set(mapping) - set(declared)
    if unknown:
        raise ConfigError(
            f"{path or '<root>'}: unknown config key(s) {sorted(unknown)} — "
            "invariant I2 requires every flag to be declared in ctrend.config "
            "and logged in DECISIONS.md"
        )
    kwargs: dict[str, Any] = {}
    for name, f in declared.items():
        if name not in mapping:
            if f.default is not MISSING or f.default_factory is not MISSING:  # type: ignore[misc]
                continue
            raise ConfigError(f"{path or '<root>'}: missing required key {name!r}")
        kwargs[name] = _coerce(mapping[name], f.type, f"{path}.{name}" if path else name)
    return cls(**kwargs)


_SECTION_TYPES: dict[str, type] = {
    c.__name__: c
    for c in (
        SampleConfig,
        UniverseConfig,
        ReturnsConfig,
        IndicatorsConfig,
        LambdaGridConfig,
        ElasticNetConfig,
        SignalConfig,
        HedgeConfig,
        PortfolioConfig,
        CostsConfig,
        EvaluationConfig,
    )
    if is_dataclass(c)
}


def load_config(path: str | Path) -> Config:
    """Load and validate a YAML config. Unknown keys raise :class:`ConfigError`."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path}: top level is not a mapping")
    digest = hashlib.sha256(
        yaml.safe_dump(_plain(raw), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    cfg = _build(Config, dict(raw), "")
    object.__setattr__(cfg, "hash", digest)
    object.__setattr__(cfg, "source_path", str(path))
    return cfg


def _plain(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    return obj
