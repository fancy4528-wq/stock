"""Build day-level regime / volatility / event tags from research outputs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

from quantagent.agents.schemas.views import MarketBrief
from quantagent.agents.tools.research_facts import ResearchFacts
from quantagent.evaluation.decisions.types import DecisionContextDay, VolatilityBucket

# Same 1.5% index move MacroAgent uses for risk_on / risk_off.
_HIGH_MOVE = 0.015
_LOW_MOVE = 0.005
# docs/08 §8.1 example: news_volume > 10 → high_news
_HIGH_NEWS = 10


def volatility_from_index_return(ret_1d: float) -> VolatilityBucket:
    """Bucket a single-day index move. High / low edges match MacroAgent thresholds."""
    mag = abs(float(ret_1d))
    if mag >= _HIGH_MOVE:
        return "high"
    if mag <= _LOW_MOVE:
        return "low"
    return "normal"


def event_tags_from(
    *,
    regime_drivers: Sequence[str] | None = None,
    news_count: int | None = None,
) -> list[str]:
    """Stable event labels stored beside regime. Order is fixed for diffs."""
    tags: list[str] = []
    drivers = list(regime_drivers or [])
    if any(str(d).startswith("市场冲击[") for d in drivers):
        tags.append("market_shock")
    if news_count is not None and int(news_count) > _HIGH_NEWS:
        tags.append("high_news")
    return tags


def context_from_research(
    *,
    as_of: date,
    run_id: str,
    brief: MarketBrief,
    facts: ResearchFacts,
    origin: Literal["live", "synthetic"] = "live",
    code_version: str = "dev",
    regime_drivers: Sequence[str] | None = None,
) -> DecisionContextDay:
    """Snapshot the conditions visible on the decision date (PIT)."""
    drivers = (
        list(regime_drivers) if regime_drivers is not None else _drivers_from_brief(brief)
    )
    return DecisionContextDay(
        as_of=as_of,
        run_id=run_id,
        origin=origin,
        code_version=code_version,
        market_regime=brief.regime,
        volatility=volatility_from_index_return(facts.index_return_1d),
        event_tags=event_tags_from(
            regime_drivers=drivers,
            news_count=facts.news_count,
        ),
        index_return_1d=float(facts.index_return_1d),
        news_count=int(facts.news_count),
    )


def synthetic_context(
    *,
    as_of: date,
    run_id: str,
    code_version: str = "dev",
) -> DecisionContextDay:
    """Deterministic tags for the synthetic daily pipeline."""
    return DecisionContextDay(
        as_of=as_of,
        run_id=run_id,
        origin="synthetic",
        code_version=code_version,
        market_regime="neutral",
        volatility="normal",
        event_tags=[],
        index_return_1d=0.0,
        news_count=0,
    )


def _drivers_from_brief(brief: MarketBrief) -> list[str]:
    """Chief brief keeps regime_note; shock markers live in the note text."""
    note = (brief.regime_note or "").strip()
    if not note:
        return []
    return [part.strip() for part in note.split("；") if part.strip()]
