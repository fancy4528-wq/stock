"""Result contracts for single-factor evaluation."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ICSummary(BaseModel):
    """Aggregate statistics over a daily IC series."""

    ic_mean: float
    ic_std: float
    icir: float
    ic_t_stat: float
    ic_p_value: float
    ic_positive_ratio: float
    n_periods: int


class QuantileSummary(BaseModel):
    """Cross-sectional quantile / long-short results."""

    n_quantiles: int
    quantile_returns: list[float]
    monotonicity: float
    long_short_return: float
    long_short_sharpe: float


class FactorTestResult(BaseModel):
    """Full single-factor evaluation result (docs/07-quant-engine.md §3.1)."""

    factor_code: str
    period: tuple[date, date]
    horizon_days: int = 5
    n_quantiles: int = 5

    # IC
    ic_mean: float
    ic_std: float
    icir: float
    ic_t_stat: float
    ic_p_value: float
    ic_positive_ratio: float
    n_ic_periods: int = 0

    # Quantile
    quantile_returns: list[float] = Field(default_factory=list)
    monotonicity: float = 0.0
    long_short_return: float = 0.0
    long_short_sharpe: float = 0.0

    # Stability
    ic_decay: list[float] = Field(default_factory=list)
    ic_decay_horizons: list[int] = Field(default_factory=list)
    ic_by_year: dict[int, float] = Field(default_factory=dict)
    ic_by_regime: dict[str, float] = Field(default_factory=dict)

    # Turnover proxies
    autocorrelation: float = 0.0
    turnover_estimate: float = 0.0

    # Cross-factor
    correlations: dict[str, float] = Field(default_factory=dict)

    # Admission
    admission_pass: bool = False
    admission_notes: list[str] = Field(default_factory=list)
