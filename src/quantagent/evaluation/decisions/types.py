"""Day-level decision context tags (docs/08 §8.1–8.2).

Postgres ``decision_journal`` is the long-term store. Until that migration
lands, live tags accumulate in an append-only JSONL next to the shadow
journals so monthly review §5 can fill during the Gate 4 observation window.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

MarketRegime = Literal["risk_on", "risk_off", "neutral", "transition"]
VolatilityBucket = Literal["high", "normal", "low"]


class DecisionContextDay(BaseModel):
    """Market condition snapshot for one decision date.

    Accuracy is joined later from Agent scores + forward returns. This row is
    never rewritten: a recorded ``as_of`` stays as it was on that day.
    """

    as_of: date
    run_id: str
    origin: Literal["live", "synthetic"] = "live"
    code_version: str = "dev"
    market_regime: MarketRegime
    volatility: VolatilityBucket
    event_tags: list[str] = Field(default_factory=list)
    index_return_1d: float | None = None
    news_count: int | None = None
