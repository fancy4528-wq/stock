"""Research shortlist seeds (Stage 4a input / deterministic Agent facts)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CandidateSeed(BaseModel):
    symbol: str
    name: str
    role: str = "constituent"
    preliminary_score: float = 0.5


class SectorSeed(BaseModel):
    code: str
    name: str
    ret_1d: float = 0.0
    ret_20d: float = 0.0
    candidates: list[CandidateSeed] = Field(default_factory=list)


class StockSeed(BaseModel):
    symbol: str
    name: str
    sector_code: str
    ret_20d: float = 0.0
    preliminary_score: float = 0.5


class ResearchFacts(BaseModel):
    """Deterministic inputs for skeleton Agents (no live DB required)."""

    as_of: date
    market: str = "CN"
    index_return_1d: float = 0.0
    n_up: int = 0
    n_down: int = 0
    total_amount: float = 0.0
    industries: list[SectorSeed] = Field(default_factory=list)
    themes: list[SectorSeed] = Field(default_factory=list)
    stocks: list[StockSeed] = Field(default_factory=list)
    macro_note: str = "skeleton neutral macro"
    news_count: int = 0
    events_count: int = 0
