"""Portfolio types."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateMeta(BaseModel):
    """Optional per-symbol flags used for portfolio-layer exclusion."""

    symbol: str
    is_suspended: bool = False
    is_st: bool = False
    in_blacklist: bool = False
    board: str = "main"
    industry: str | None = None
    avg_amount_20d: float | None = None
    price: float | None = None
    is_limit_up: bool = False
    is_limit_down: bool = False


class TargetPortfolio(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    cash_weight: float = 1.0
    selected: list[str] = Field(default_factory=list)
    excluded: dict[str, str] = Field(default_factory=dict)
    method: str = "equal"
