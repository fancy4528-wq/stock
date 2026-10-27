"""Signal Fusion config and score types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DEFAULT_WEIGHTS: dict[str, float] = {
    "quant": 0.20,
    "sector": 0.20,
    "stock": 0.20,
    "macro_fit": 0.20,
    "news": 0.20,
}


class FusionConfig(BaseModel):
    version: str = "equal-v1"
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    normalize: Literal["zscore", "rank", "minmax"] = "rank"
    missing_signal_policy: Literal["renormalize", "neutral", "exclude"] = "renormalize"
    regime_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)


class FusedScore(BaseModel):
    final_score: float
    components: dict[str, float] = Field(default_factory=dict)
    weights_used: dict[str, float] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
