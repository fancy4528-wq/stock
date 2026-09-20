"""Extract shadow_agent target scores from research Agent outputs."""

from __future__ import annotations

from collections.abc import Sequence

from quantagent.agents.schemas.views import MarketBrief, StockView


def scores_from_brief(brief: MarketBrief | None) -> dict[str, float]:
    """Map ``MarketBrief.stock_ranking`` → symbol scores for Top-N selection."""
    if brief is None:
        return {}
    out: dict[str, float] = {}
    for row in brief.stock_ranking:
        # Prefer higher score; confidence only breaks ties via slight uplift.
        out[row.symbol] = float(row.score) + 0.01 * float(row.confidence)
    return out


def scores_from_stock_views(views: Sequence[StockView]) -> dict[str, float]:
    """Fallback when Chief aborted but StockViews exist."""
    out: dict[str, float] = {}
    for v in views:
        out[v.symbol] = float(v.score) + 0.01 * float(v.confidence)
    return out
