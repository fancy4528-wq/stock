"""Agent tools for Reporter + research Agents."""

from quantagent.agents.tools.dispatch import ToolError, ToolRegistry
from quantagent.agents.tools.facts_builder import build_research_facts
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
from quantagent.agents.tools.research_db import (
    DB_TOOL_NAMES,
    get_announcements,
    get_financial_indicators,
    get_financials,
    get_index_prices,
    get_macro_series,
    get_market_breadth,
    get_money_flow,
    get_northbound_flow,
    get_peers,
    get_policy_news,
    get_sector_constituents,
    get_sector_flow,
    get_sector_news,
    get_sector_prices,
    get_stock_events,
    get_stock_news,
    get_stock_prices,
    get_valuation,
    register_db_tools,
)
from quantagent.agents.tools.research_facts import (
    CandidateSeed,
    ResearchFacts,
    SectorSeed,
    StockSeed,
)
from quantagent.core.repository.pit import PITRepository
from quantagent.knowledge.embedding.base import Embedder


def build_default_tool_registry(
    *,
    include_knowledge: bool = True,
    include_db: bool = True,
    repo: PITRepository | None = None,
    embedder: Embedder | None = None,
) -> ToolRegistry:
    """Registry with PIT-injected tools.

    Offline smoke/tests: ``include_knowledge=False, include_db=False``.
    Live research: both True (DB tools hit ``PITRepository``).
    """
    from functools import partial

    reg = ToolRegistry()
    if include_knowledge:
        if repo is not None or embedder is not None:
            reg.register(
                "search_knowledge",
                partial(search_knowledge, repo=repo, embedder=embedder),
            )
        else:
            reg.register("search_knowledge", search_knowledge)
    if include_db:
        register_db_tools(reg, repo=repo)
    return reg


__all__ = [
    "CandidateSeed",
    "DB_TOOL_NAMES",
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
    "build_research_facts",
    "get_announcements",
    "get_factor_performance",
    "get_financial_indicators",
    "get_financials",
    "get_index_prices",
    "get_macro_series",
    "get_market_breadth",
    "get_market_overview",
    "get_money_flow",
    "get_northbound_flow",
    "get_peers",
    "get_policy_news",
    "get_sector_constituents",
    "get_sector_flow",
    "get_sector_news",
    "get_sector_performance",
    "get_sector_prices",
    "get_shadow_status",
    "get_stock_events",
    "get_stock_news",
    "get_stock_prices",
    "get_valuation",
    "register_db_tools",
    "search_knowledge",
]
