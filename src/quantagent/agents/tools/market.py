"""Report tool inputs built from a ReportBundle (no live DB required for MVP)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class MarketOverview(BaseModel):
    as_of: date
    index_symbol: str = "000300.SH"
    index_close: float
    index_return_1d: float
    n_up: int
    n_down: int
    n_flat: int = 0
    total_amount: float
    amount_vs_20d: float
    avg_turnover: float
    up_down_pctile_20d: float | None = None
    amount_pctile_20d: float | None = None
    turnover_pctile_20d: float | None = None


class SectorRow(BaseModel):
    industry: str
    n_names: int
    ret_1d: float
    ret_5d: float
    ret_20d: float


class FactorRow(BaseModel):
    factor: str
    long_short_1d: float
    ic_mean_20d: float | None = None


class FactorRankRow(BaseModel):
    rank: int
    symbol: str
    name: str
    score_pctile: float
    ret_20d: float


class ShadowStatusRow(BaseModel):
    portfolio: str
    ret_1d: float
    ret_cum: float
    max_drawdown: float
    n_positions: int


class RiskNote(BaseModel):
    text: str


class QualityCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ReportBundle(BaseModel):
    """Structured facts for tools + markdown sections."""

    as_of: date
    run_id: str
    market: str = "CN"
    market_overview: MarketOverview
    sectors: list[SectorRow] = Field(default_factory=list)
    factors: list[FactorRow] = Field(default_factory=list)
    factor_ranks: list[FactorRankRow] = Field(default_factory=list)
    factor_rank_name: str = "mom_20d"
    shadow: list[ShadowStatusRow] = Field(default_factory=list)
    risk_notes: list[RiskNote] = Field(default_factory=list)
    quality: list[QualityCheck] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    code_version: str = "dev"


def get_market_overview(bundle: ReportBundle) -> MarketOverview:
    return bundle.market_overview


def get_sector_performance(bundle: ReportBundle) -> list[SectorRow]:
    return list(bundle.sectors)


def get_factor_performance(bundle: ReportBundle) -> list[FactorRow]:
    return list(bundle.factors)


def get_shadow_status(bundle: ReportBundle) -> list[ShadowStatusRow]:
    return list(bundle.shadow)
