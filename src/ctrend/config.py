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
    exclude_stablecoins: bool = True  # GT-3b — baseline filter in b05:62-74
    min_price_usd: float = 0.0  # dMinPrc, b05:20


@dataclass(frozen=True, slots=True)
class ReturnsConfig:
    truncate_lower_pct: float
    truncate_upper_pct: float
    # GT-2: the authors truncate DAILY, per-day cross-sectional, dropping to NaN.
    # "full_sample" | "expanding" are retained as sensitivity options only.
    truncation_mode: str
    truncation_scope: str  # "per_day" | "pooled" | "per_week"
    risk_free: float
    first_obs_quirk: str = "faithful"  # GT-2b — MATLAB NaN~=NaN drops each coin's first obs


@dataclass(frozen=True, slots=True)
class IndicatorsConfig:
    macd_denominator: str  # A1 -> GT-4: "slow" (code calls PPO), "fast" was the guess
    chaikin_window: int  # A2 -> GT-5: 21
    rank_map_range: tuple[float, float]
    chaikin_min_obs: int = 10  # GT-5
    cci_window: int = 20
    cci_min_obs: int = 10
    stoch_scale: str = "unit"  # GT-6 — stochK/D/RSI are [0,1], not [0,100]
    sma_warmup: str = "expanding"  # GT-7 — expanding omitnan; sma_200d non-NaN from day 1
    resample: str = "liu_year_blocks"  # GT-1 — no weekday exists
    liu_resample_lastfix: str = "corrected"  # A6 — authors' 'last' fallback reads the future

    @property
    def n(self) -> int:
        """J = 28, fixed by SPEC §4.2; not a tunable."""
        from ctrend import J_INDICATORS

        return J_INDICATORS


@dataclass(frozen=True, slots=True)
class LambdaGridConfig:
    """GT-9: the authors use 200 DATA-DEPENDENT lambdas, from ``lambda_max``
    (smallest λ zeroing all coefficients) down to ``ratio * lambda_max``,
    recomputed per rolling window. ``log_low``/``log_high`` describe the
    superseded fixed grid and are kept only for the sensitivity axis."""

    n: int
    mode: str = "data_dependent"  # "data_dependent" | "fixed"
    ratio: float = 1.0e-4
    log_low: float | None = None
    log_high: float | None = None


@dataclass(frozen=True, slots=True)
class ElasticNetConfig:
    l1_ratio: float
    lambda_grid: LambdaGridConfig
    selection: str  # must be "aicc" — I2 forbids cross-validation
    max_iter: int
    standardize: bool = True  # MATLAB lasso Standardize=true; rescale coefs back
    aicc_k: str = "nonzero"  # GT-10 — k = nonzero coefficients, NO +1


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
    # GT-8: ONE (alpha_bar, beta_bar) pair per indicator -- the mean of the 52
    # weekly WLS gammas -- applied uniformly to every training week AND to the
    # out-of-sample week. "trailing_mean" was our (incorrect) reading of §4.3.
    smoothing: str = "window_mean"
    # GT-11: only the RETURNS are cross-sectionally demeaned; the forecasts are
    # not, and the combining step fits one global intercept with no time FE.
    # Distinct from `demean_returns`, which says HOW the returns are demeaned.
    demean: str = "returns_only"
    val_fraction: float = 0.0  # dFracVal=0 -> train/test indices coincide (documented)


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
    min_cross_section: int = 25  # iMinNumCS — week voided below this
    min_assets_per_portfolio: int = 5  # iMinNumAssets
    # MATLAB quantile(...,'exact') uses (i-0.5)/n plotting positions with linear
    # interpolation -- NOT numpy.percentile's default. Breakpoints drift otherwise.
    quantile_method: str = "matlab_exact"


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
    # GT-12: the authors use plain OLS/iid t-stats (ttest, regstats). The paper's
    # alpha^LTW t = 4.22 is an OLS t; HAC would change it and could move the §7 gate.
    tstat_method: str = "ols"  # "ols" | "newey_west"
    # Breakeven TC divides by raw sum|dw| -- unhalved, no drift adjustment. This is
    # NOT the reported GKX turnover (fSingleSortMulti.m:329 vs :403-410).
    breakeven_tc_turnover: str = "raw_abs"
    validate_against_shipped_factor: bool = True  # Results/CTREND/CTREND.xlsx, 371 wks


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
        # GT-2: "daily_cross_sectional" is the authors' actual behaviour and the
        # replication default; the other two are sensitivity axes only.
        if self.returns.truncation_mode not in (
            "daily_cross_sectional",
            "full_sample",
            "expanding",
        ):
            raise ConfigError(f"unknown truncation_mode {self.returns.truncation_mode!r}")
        if self.indicators.macd_denominator not in ("slow", "fast"):
            raise ConfigError(
                f"unknown macd_denominator {self.indicators.macd_denominator!r} (GT-4)"
            )
        if self.signal.smoothing not in ("window_mean", "trailing_mean"):
            raise ConfigError(f"unknown signal.smoothing {self.signal.smoothing!r} (GT-8)")
        if self.indicators.liu_resample_lastfix not in ("corrected", "faithful"):
            raise ConfigError(
                f"unknown liu_resample_lastfix {self.indicators.liu_resample_lastfix!r} (A6)"
            )
        if self.mode == "live" and self.indicators.liu_resample_lastfix == "faithful":
            # A6 reproduces a real look-ahead bug in the authors' resampler. It is
            # available for replication fidelity only; live mode must satisfy I1.
            raise ConfigError(
                "liu_resample_lastfix='faithful' reproduces the authors' look-ahead "
                "bug (A6) and is not permitted in live mode (invariant I1)"
            )


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
