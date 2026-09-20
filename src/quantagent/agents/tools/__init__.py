"""Agent tools for Reporter + research Agents."""

from quantagent.agents.tools.dispatch import ToolError, ToolRegistry
from quantagent.agents.tools.knowledge import search_knowledge
from quantagent.agents.tools.market import (
    FactorRankRow,
    FactorRow,
    MarketOverview,
    QualityCheck,
    ReportBundle,
    RiskNote,
    SectorRow,
    ShadowStatusRow,
    get_factor_performance,
    get_market_overview,
    get_sector_performance,
    get_shadow_status,
)
from quantagent.agents.tools.research_facts import (
    CandidateSeed,
    ResearchFacts,
    SectorSeed,
    StockSeed,
)


def build_default_tool_registry(
    *,
    include_knowledge: bool = True,
) -> ToolRegistry:
    """Registry with PIT-injected tools. Knowledge search is optional for offline tests."""
    reg = ToolRegistry()
    if include_knowledge:
        reg.register("search_knowledge", search_knowledge)
    return reg


__all__ = [
    "CandidateSeed",
    "FactorRankRow",
    "FactorRow",
    "MarketOverview",
    "QualityCheck",
    "ReportBundle",
    "ResearchFacts",
    "RiskNote",
    "SectorRow",
    "SectorSeed",
    "ShadowStatusRow",
    "StockSeed",
    "ToolError",
    "ToolRegistry",
    "build_default_tool_registry",
    "get_factor_performance",
    "get_market_overview",
    "get_sector_performance",
    "get_shadow_status",
    "search_knowledge",
]
