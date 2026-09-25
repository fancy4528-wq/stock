"""Monitor shared types (P2a)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class QuoteSnapshot(BaseModel):
    """Intraday (or demo) quote used by price triggers — not historical PIT."""

    symbol: str
    last: float
    prev_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    volume_avg_5d: float | None = None
    ma60: float | None = None
    prev_ma60: float | None = None
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_suspended: bool = False
    ts: datetime | None = None
    name: str | None = None

    @property
    def pct_change(self) -> float | None:
        if self.prev_close is None or self.prev_close <= 0:
            return None
        return self.last / self.prev_close - 1.0

    @property
    def volume_ratio_5d(self) -> float | None:
        if self.volume is None or self.volume_avg_5d is None or self.volume_avg_5d <= 0:
            return None
        return self.volume / self.volume_avg_5d


class HoldingMetrics(BaseModel):
    """Derived metrics for one position + quote."""

    symbol: str
    name: str
    quantity: float
    avg_cost: float
    last: float
    holding_return: float
    entry_high: float
    drawdown_from_entry_high: float
    weight: float
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_suspended: bool = False
    pct_change: float | None = None
    volume_ratio_5d: float | None = None
    ma60: float | None = None
    prev_close: float | None = None
    prev_ma60: float | None = None
    target_price: float | None = None


Severity = Literal["critical", "high", "medium", "info"]


class TriggerHit(BaseModel):
    """A fired price/risk trigger candidate (pre-suppression / notify)."""

    code: str
    severity: Severity
    symbol: str
    title: str
    message: str
    analysis_level: Literal["L1"] = "L1"
    cost_usd: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)
    cooldown_hours: float = 24.0
