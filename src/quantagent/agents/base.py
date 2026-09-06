"""Agent protocol and shared contracts."""

from __future__ import annotations

from datetime import date
from typing import Protocol, TypeVar

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """Traceable evidence reference. Judgements without evidence are invalid."""

    evidence_id: str
    kind: str  # "news" | "financial" | "factor" | "price" | "shadow" | "quality"
    ref_id: str
    excerpt: str | None = Field(default=None, max_length=400)
    as_of: date


class AgentContext(BaseModel):
    """Runtime context. ``as_of`` is required end-to-end."""

    as_of: date
    market: str
    run_id: str
    token_budget_usd: float = 1.0
    code_version: str = "dev"
    upstream: dict[str, BaseModel] = Field(default_factory=dict)


TOut_co = TypeVar("TOut_co", bound=BaseModel, covariant=True)


class Agent(Protocol[TOut_co]):
    name: str
    tier: str

    async def run(self, ctx: AgentContext) -> TOut_co: ...
