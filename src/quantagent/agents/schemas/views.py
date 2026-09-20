"""P2 research Agent output schemas (Macro / Sector / Stock / Chief)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from quantagent.agents.base import Evidence

# ── shared building blocks ───────────────────────────────────────────


class DimScore(BaseModel):
    score: float = Field(ge=0, le=1)
    note: str = Field(max_length=150)
    evidence_refs: list[str] = Field(default_factory=list)


class ArgumentPoint(BaseModel):
    point: str = Field(max_length=200)
    strength: Literal["weak", "moderate", "strong"]
    evidence_refs: list[str] = Field(min_length=1)


class RiskNote(BaseModel):
    risk: str
    severity: Literal["low", "medium", "high"]
    probability: Literal["low", "medium", "high"]
    monitorable: bool = Field(description="是否有可观测的前兆指标")


class StockCandidate(BaseModel):
    symbol: str
    name: str
    role: str = Field(description="在该板块中的定位，如'龙头'/'弹性标的'")
    preliminary_score: float = Field(ge=0, le=1)
    reason: str = Field(max_length=150)


# ── MacroAgent ───────────────────────────────────────────────────────


class DimensionView(BaseModel):
    direction: Literal["improving", "deteriorating", "stable", "unclear"]
    score: float = Field(ge=-1, le=1)
    note: str = Field(max_length=200)
    evidence_refs: list[str]


class SectorImpact(BaseModel):
    industry_code: str
    impact: float = Field(ge=-1, le=1)
    reason: str = Field(max_length=150)
    confidence: float = Field(ge=0, le=1)


class UpcomingEvent(BaseModel):
    expected_date: date | None = None
    description: str
    watch_reason: str


class MacroView(BaseModel):
    as_of: date
    regime: Literal["risk_on", "risk_off", "neutral", "transition"]
    regime_confidence: float = Field(ge=0, le=1)
    regime_drivers: list[str] = Field(min_length=1)

    liquidity: DimensionView
    growth: DimensionView
    inflation: DimensionView
    policy: DimensionView
    external: DimensionView

    sector_impacts: list[SectorImpact] = Field(default_factory=list)
    upcoming_events: list[UpcomingEvent] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)
    degraded: bool = False
    degrade_reason: str | None = None


# ── Industry / Theme (SectorView) ────────────────────────────────────


class SectorDimensions(BaseModel):
    fundamental: DimScore
    valuation: DimScore
    momentum: DimScore
    flow: DimScore
    news_sentiment: DimScore
    macro_fit: DimScore


class ThemeLifecycle(BaseModel):
    stage: Literal["emerging", "acceleration", "peak", "declining", "dormant"]
    days_since_activation: int = Field(ge=0)
    evidence: str = Field(max_length=300)


class SectorView(BaseModel):
    as_of: date
    sector_type: Literal["industry", "theme"]
    sector_code: str
    sector_name: str

    score: float = Field(ge=0, le=1, description="综合吸引力，0.5 为中性")
    confidence: float = Field(ge=0, le=1)
    horizon: Literal["1w", "1m", "3m", "6m"]

    thesis: str = Field(max_length=800)
    dimensions: SectorDimensions
    bull_points: list[ArgumentPoint] = Field(min_length=1)
    bear_points: list[ArgumentPoint] = Field(min_length=1)
    key_uncertainties: list[str] = Field(default_factory=list)
    candidates: list[StockCandidate] = Field(default_factory=list, max_length=10)
    risks: list[RiskNote] = Field(default_factory=list)
    theme_lifecycle: ThemeLifecycle | None = None
    evidence: list[Evidence] = Field(min_length=2)


# ── StockAgent ───────────────────────────────────────────────────────


class StockDimensions(BaseModel):
    fundamental: DimScore
    valuation: DimScore
    growth: DimScore
    quality: DimScore
    momentum: DimScore
    news: DimScore
    sector_fit: DimScore


class Catalyst(BaseModel):
    description: str
    expected_timing: str
    impact: Literal["low", "medium", "high"]
    probability: Literal["low", "medium", "high"]


class RedFlag(BaseModel):
    flag: str
    category: Literal[
        "accounting",
        "governance",
        "liquidity",
        "concentration",
        "regulatory",
        "competitive",
    ]
    severity: Literal["watch", "concern", "serious"]
    evidence_refs: list[str] = Field(min_length=1)


class FinancialHealth(BaseModel):
    revenue_trend: Literal["accelerating", "growing", "flat", "declining"]
    margin_trend: Literal["expanding", "stable", "compressing"]
    cash_conversion: Literal["strong", "adequate", "weak"]
    leverage: Literal["low", "moderate", "high", "concerning"]
    notes: str = Field(max_length=300)


class StockView(BaseModel):
    as_of: date
    symbol: str
    name: str

    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    horizon: Literal["1w", "1m", "3m", "6m"]

    thesis: str = Field(max_length=800)
    dimensions: StockDimensions
    bull_points: list[ArgumentPoint] = Field(min_length=1)
    bear_points: list[ArgumentPoint] = Field(min_length=1)
    catalysts: list[Catalyst] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    financial_health: FinancialHealth
    risks: list[RiskNote] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=3)


# ── ChiefAgent ───────────────────────────────────────────────────────


class RankedSector(BaseModel):
    rank: int
    sector_code: str
    sector_name: str
    sector_type: Literal["industry", "theme"]
    score: float
    confidence: float
    one_liner: str = Field(max_length=120)
    change_from_prev: Literal["up", "down", "unchanged", "new"] = "new"


class RankedStock(BaseModel):
    rank: int
    symbol: str
    name: str
    sector_code: str
    score: float
    confidence: float
    action_hint: Literal["strong_candidate", "candidate", "watch", "avoid"]
    one_liner: str = Field(max_length=120)


class AllocationStance(BaseModel):
    """方向性建议，不是具体权重。权重由 PortfolioEngine 算。"""

    equity_stance: Literal["aggressive", "moderate", "defensive", "cautious"]
    rationale: str = Field(max_length=300)
    preferred_sectors: list[str] = Field(default_factory=list)
    avoid_sectors: list[str] = Field(default_factory=list)


class Disagreement(BaseModel):
    subject: str
    positions: list[str]
    resolution: str


class WatchItem(BaseModel):
    symbol: str | None = None
    sector_code: str | None = None
    reason: str = Field(max_length=200)
    trigger: str = Field(max_length=150)


class InputsSummary(BaseModel):
    macro_view_id: int | None = None
    sector_view_ids: list[int] = Field(default_factory=list)
    stock_view_ids: list[int] = Field(default_factory=list)
    news_count: int = 0
    events_count: int = 0
    data_as_of: date
    data_quality_note: str | None = None
    sector_count: int = 0
    stock_count: int = 0
    skipped_sectors: list[str] = Field(default_factory=list)
    skipped_stocks: list[str] = Field(default_factory=list)


class MarketBrief(BaseModel):
    as_of: date
    run_id: str

    market_summary: str = Field(max_length=600)
    regime: Literal["risk_on", "risk_off", "neutral", "transition"]
    regime_note: str = Field(max_length=300)

    sector_ranking: list[RankedSector] = Field(min_length=1)
    stock_ranking: list[RankedStock] = Field(default_factory=list)
    allocation_stance: AllocationStance
    disagreements: list[Disagreement] = Field(default_factory=list)
    key_uncertainties: list[str] = Field(min_length=1)
    watchlist: list[WatchItem] = Field(default_factory=list)
    inputs_summary: InputsSummary
    evidence: list[Evidence] = Field(min_length=1)
