"""Unit tests for P2 multi-Agent skeleton (schemas, tools, orchestrator)."""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.chief.agent import ChiefAgent
from quantagent.agents.fixtures import sample_research_facts
from quantagent.agents.macro.agent import MacroAgent, neutral_macro_view
from quantagent.agents.orchestrator import Orchestrator
from quantagent.agents.screener import screen_shortlist
from quantagent.agents.sector.industry import IndustryAgent, ThemeAgent
from quantagent.agents.stock.agent import StockAgent
from quantagent.agents.tools.dispatch import ToolError, ToolRegistry
from quantagent.shared.errors import AgentError


@pytest.fixture
def facts():
    return sample_research_facts(date(2026, 9, 12))


@pytest.fixture
def ctx(facts):
    return AgentContext(
        as_of=facts.as_of,
        market=facts.market,
        run_id="20260912-cn-daily",
    )


def test_tool_registry_injects_as_of_and_rejects_agent_as_of(ctx):
    seen: dict[str, object] = {}

    def fake_tool(*, query: str, as_of: date, top_k: int = 5) -> list[str]:
        seen["as_of"] = as_of
        seen["query"] = query
        seen["top_k"] = top_k
        return ["ok"]

    reg = ToolRegistry()
    reg.register("search_knowledge", fake_tool)
    out = reg.call("search_knowledge", {"query": "宏观", "top_k": 3}, ctx)
    assert out == ["ok"]
    assert seen["as_of"] == ctx.as_of
    assert seen["query"] == "宏观"

    with pytest.raises(ToolError, match="must not pass as_of"):
        reg.call(
            "search_knowledge",
            {"query": "x", "as_of": date(2099, 1, 1)},
            ctx,
        )


def test_screener_top_n(facts):
    shortlist = screen_shortlist(facts, max_industries=2, max_themes=1)
    assert len(shortlist.industries) == 2
    assert len(shortlist.themes) == 1
    # Highest |ret_20d| industry first
    assert shortlist.industries[0] == "801080"


@pytest.mark.asyncio
async def test_macro_industry_theme_stock_views(facts, ctx):
    macro = await MacroAgent(facts).run(ctx)
    assert macro.regime in {"risk_on", "risk_off", "neutral", "transition"}
    assert macro.evidence

    industry = await IndustryAgent(facts.industries[0]).run(ctx)
    assert industry.sector_type == "industry"
    assert industry.bear_points

    theme = await ThemeAgent(facts.themes[0]).run(ctx)
    assert theme.sector_type == "theme"
    assert theme.theme_lifecycle is not None

    stock = await StockAgent(facts.stocks[0]).run(ctx)
    assert stock.symbol == "002415.SZ"
    assert len(stock.evidence) >= 3


@pytest.mark.asyncio
async def test_orchestrator_happy_path(facts):
    orch = Orchestrator(max_stocks=5, max_concurrency=3, tools=ToolRegistry())
    result = await orch.run_daily(facts.as_of, facts.market, facts)
    assert not result.aborted
    assert result.brief is not None
    assert result.brief.regime
    assert result.brief.sector_ranking
    assert result.brief.allocation_stance.equity_stance
    assert result.brief.inputs_summary.sector_count >= 1


@pytest.mark.asyncio
async def test_orchestrator_skips_failed_stock(facts, monkeypatch):
    from quantagent.agents import orchestrator as orch_mod

    original = orch_mod.StockAgent

    class FlakyStock(original):  # type: ignore[valid-type, misc]
        async def run(self, ctx: AgentContext):
            if self._seed.symbol == "002415.SZ":
                raise AgentError("boom")
            return await super().run(ctx)

    monkeypatch.setattr(orch_mod, "StockAgent", FlakyStock)
    orch = Orchestrator(max_stocks=10, tools=ToolRegistry())
    result = await orch.run_daily(facts.as_of, facts.market, facts)
    assert not result.aborted
    assert "002415.SZ" in result.skipped_stocks
    assert result.brief is not None
    symbols = {s.symbol for s in result.brief.stock_ranking}
    assert "002415.SZ" not in symbols


@pytest.mark.asyncio
async def test_macro_failure_degrades_to_neutral(facts, monkeypatch):
    from quantagent.agents import orchestrator as orch_mod

    class BoomMacro:
        name = "macro"
        tier = "medium"

        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

        async def run(self, ctx: AgentContext):
            raise AgentError("macro down")

    monkeypatch.setattr(orch_mod, "MacroAgent", BoomMacro)
    orch = Orchestrator(max_stocks=3, tools=ToolRegistry())
    result = await orch.run_daily(facts.as_of, facts.market, facts)
    assert not result.aborted
    assert result.brief is not None
    assert result.brief.regime == "neutral"
    assert any(d.action == "neutral_macro" for d in result.degradations)
    assert result.brief.inputs_summary.data_quality_note


@pytest.mark.asyncio
async def test_chief_abort_when_no_sectors(ctx):
    chief = ChiefAgent()
    macro = neutral_macro_view(ctx, reason="x")
    with pytest.raises(AgentError, match="SectorView"):
        await chief.run(ctx.model_copy(update={"upstream": {"macro": macro}}))


@pytest.mark.asyncio
async def test_neutral_macro_view_marked_degraded(ctx):
    view = neutral_macro_view(ctx, reason="timeout")
    assert view.degraded is True
    assert view.regime == "neutral"


@pytest.mark.asyncio
async def test_macro_calls_search_knowledge_via_registry(facts, ctx):
    calls: list[dict] = []

    def fake_search(*, query: str, as_of: date, top_k: int = 5, **kwargs):
        calls.append({"query": query, "as_of": as_of, "top_k": top_k, **kwargs})
        return [{"doc_ref": "news:1", "content": "政策"}]

    reg = ToolRegistry()
    reg.register("search_knowledge", fake_search)
    view = await MacroAgent(facts, tools=reg).run(ctx)
    assert calls
    assert calls[0]["as_of"] == ctx.as_of
    assert "知识库命中" in (view.evidence[1].excerpt or "")
