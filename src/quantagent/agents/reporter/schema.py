"""ReporterAgent output schema (factual daily report — no investment advice)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from quantagent.agents.base import Evidence


class Observation(BaseModel):
    """Notable fact only — no causal inference."""

    statement: str = Field(max_length=200)
    metric: str
    value: float
    evidence_refs: list[str] = Field(min_length=1)


class DailyReport(BaseModel):
    as_of: date
    run_id: str

    market_summary: str = Field(max_length=400, description="Facts only, no judgement")
    sector_summary: str = Field(max_length=400)
    factor_summary: str = Field(max_length=300)
    notable_observations: list[Observation] = Field(default_factory=list, max_length=5)
    data_quality_note: str | None = None

    evidence: list[Evidence] = Field(min_length=3)
