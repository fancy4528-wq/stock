"""Monthly self-evaluation inputs (docs/08 §8.2)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from quantagent.evaluation.agent.types import AgentEvalResult
from quantagent.evaluation.signals.types import SignalCorrResult


class ShadowMonthRow(BaseModel):
    """One shadow portfolio inside a calendar month."""

    portfolio: str
    n_days: int
    start: date | None = None
    end: date | None = None
    ret_month: float | None = None
    ret_cum: float | None = None
    max_drawdown: float | None = None
    nav: float | None = None
    n_unfilled: int = 0


class FactorHealth(BaseModel):
    """Recent IC against the frozen historical IC (docs/07 §3.3).

    ``weakening`` is a sign flip, or a recent absolute IC below half the
    historical absolute IC. Missing recent IC stays ``unknown`` and is not
    treated as a failure.
    """

    factor: str
    hist_ic: float | None = None
    recent_ic: float | None = None
    decay_ratio: float | None = None
    status: Literal["healthy", "weakening", "unknown"] = "unknown"


class ConditionAccuracy(BaseModel):
    """One regime / volatility / event bucket. Empty until a decision journal exists."""

    condition: str
    n: int
    accuracy_5d: float | None = None


class CostSummary(BaseModel):
    """LLM spend whose run date falls in the month."""

    n_rows: int = 0
    usd: float = 0.0
    by_allocation: dict[str, float] = Field(default_factory=dict)
    note: str = ""


class MonthlyReview(BaseModel):
    """One calendar month. Generating it does not change Fusion weights."""

    month: str
    period: tuple[date, date]
    shadows: list[ShadowMonthRow] = Field(default_factory=list)
    shadow_warnings: list[str] = Field(default_factory=list)
    signals: SignalCorrResult = Field(default_factory=SignalCorrResult)
    agent: AgentEvalResult | None = None
    agent_note: str = ""
    factors: list[FactorHealth] = Field(default_factory=list)
    factor_note: str = ""
    conditions: list[ConditionAccuracy] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    costs: CostSummary = Field(default_factory=CostSummary)
    trading_cost_note: str = ""
