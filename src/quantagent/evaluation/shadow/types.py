"""Shadow Portfolio types."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ShadowPortfolioId = Literal["shadow_baseline", "shadow_factor"]


class ShadowDayRecord(BaseModel):
    """One trading-day snapshot for a shadow portfolio (append-only)."""

    portfolio: ShadowPortfolioId
    as_of: date
    run_id: str
    strategy_version: str
    code_version: str = "dev"

    nav: float
    cash: float
    ret_1d: float
    ret_cum: float
    max_drawdown: float
    n_positions: int
    weights: dict[str, float] = Field(default_factory=dict)
    unfilled: list[dict[str, str | float]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ShadowConfig(BaseModel):
    initial_cash: float = 1_000_000.0
    baseline_n: int = 50
    factor_top_n: int = 15
    factor_name: str = "mom_20d"
    strategy_version: str = "mvp-w8-v1"
    rebalance: Literal["daily"] = "daily"
