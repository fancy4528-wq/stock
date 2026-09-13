"""NewsExtractor output schema (extract, do not opine)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "earnings",
    "guidance",
    "policy",
    "regulation",
    "product",
    "contract",
    "mna",
    "management",
    "capacity",
    "price_change",
    "litigation",
    "shareholding",
    "rating",
    "macro",
    "other",
]

RelationType = Literal[
    "supplier",
    "customer",
    "competitor",
    "peer",
    "parent",
    "subsidiary",
]


class Figure(BaseModel):
    """Key numeric claim from the text (for validation / quant)."""

    label: str
    value: float
    unit: str
    period: str | None = None
    raw: str | None = Field(default=None, description="Matched span in source text")


class RelatedEntity(BaseModel):
    symbol: str
    relation: RelationType
    direction: Literal["positive", "negative", "neutral"] = "neutral"


class EventExtraction(BaseModel):
    """Structured event from a single news / announcement item."""

    is_relevant: bool = Field(description="Whether related to equity investing")
    event_type: EventType
    summary: str = Field(max_length=200, description="One-line factual summary")

    primary_symbols: list[str] = Field(default_factory=list)
    related_symbols: list[RelatedEntity] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)

    direction: Literal["positive", "negative", "neutral", "unclear"] = "unclear"
    magnitude: Literal["minor", "moderate", "major"] = "moderate"
    horizon: Literal["immediate", "short", "medium", "long"] = "short"
    confidence: float = Field(default=0.5, ge=0, le=1)

    figures: list[Figure] = Field(default_factory=list)
