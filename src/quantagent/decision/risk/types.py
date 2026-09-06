"""Risk types and portfolio state."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class RiskDecision(StrEnum):
    APPROVE = "approve"
    MODIFY = "modify"
    REJECT = "reject"


class RiskViolation(BaseModel):
    rule_code: str
    severity: Literal["hard", "soft"] = "hard"
    detail: str
    symbol: str | None = None
    action: Literal["reject", "clip", "scale", "reject_all"] = "reject"


class Position(BaseModel):
    symbol: str
    quantity: float
    sellable_qty: float
    market_value: float = 0.0
    cost_price: float = 0.0
    industry: str | None = None
    board: str = "main"


class PortfolioState(BaseModel):
    account_id: int = 0
    as_of: date
    cash: float = 0.0
    positions: dict[str, Position] = Field(default_factory=dict)
    total_value: float = 0.0
    peak_value: float = 0.0
    current_drawdown: float = 0.0
    consecutive_loss_days: int = 0
    turnover_mtd: float = 0.0
    is_halted: bool = False
    halt_reason: str | None = None

    def sellable_qty(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        if pos is None:
            return 0.0
        return float(pos.sellable_qty)

    def weight(self, symbol: str) -> float:
        if self.total_value <= 0:
            return 0.0
        pos = self.positions.get(symbol)
        if pos is None:
            return 0.0
        return float(pos.market_value / self.total_value)


class SecurityContext(BaseModel):
    """Cross-sectional context for risk checks on a given as_of."""

    symbol: str
    is_st: bool = False
    is_suspended: bool = False
    is_limit_up: bool = False
    is_limit_down: bool = False
    industry: str | None = None
    board: str = "main"
    avg_amount_20d: float | None = None
    price: float | None = None


class RiskResult(BaseModel):
    decision: RiskDecision
    original_target: dict[str, float]
    final_target: dict[str, float]
    violations: list[RiskViolation] = Field(default_factory=list)
    config_hash: str = ""
