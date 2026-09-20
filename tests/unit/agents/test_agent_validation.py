"""Unit tests for Gate 2 Agent output validation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.agents.base import AgentContext, Evidence
from quantagent.agents.fixtures import sample_research_facts
from quantagent.agents.macro.agent import MacroAgent
from quantagent.agents.orchestrator import Orchestrator
from quantagent.agents.schemas.views import DimensionView, MacroView
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.trace import AgentTrace, bind_trace
from quantagent.agents.validation import (
    check_evidence_ids_exist,
    check_evidence_pit,
    check_figures_traceable,
    extract_floats,
    validate_agent_output,
)


@pytest.fixture
def facts():
    return sample_research_facts(date(2026, 9, 12))


@pytest.fixture
def ctx(facts):
    return AgentContext(as_of=facts.as_of, market=facts.market, run_id="val-test")


def _macro_scaffold(as_of: date, *, evidence: list[Evidence] | None = None) -> MacroView:
    unclear = DimensionView(
        direction="unclear",
        score=0.0,
        note="test",
        evidence_refs=["ev-1"],
    )
    ev = evidence or [
        Evidence(
            evidence_id="ev-1",
            kind="price",
            ref_id="idx",
            excerpt="index_return_1d=+0.0120 up=1200 down=800",
            as_of=as_of,
        )
    ]
    return MacroView(
        as_of=as_of,
        regime="neutral",
        regime_confidence=0.5,
        regime_drivers=["指数日收益 +1.20%", "涨跌家数差 400"],
        liquidity=unclear,
        growth=unclear,
        inflation=unclear,
        policy=unclear,
        external=unclear,
        evidence=ev,
    )


def test_extract_floats_percent_and_sign() -> None:
    vals = extract_floats("收益 +1.20% 家数 400")
    assert any(abs(v - 0.012) < 1e-6 for v in vals)
    assert 400.0 in vals


def test_evidence_pit_rejects_future(ctx) -> None:
    view = _macro_scaffold(
        ctx.as_of,
        evidence=[
            Evidence(
                evidence_id="ev-1",
                kind="price",
                ref_id="x",
                excerpt="ok",
                as_of=ctx.as_of + timedelta(days=1),
            )
        ],
    )
    # Fix refs for dangling check — still future as_of
    view.liquidity.evidence_refs = ["ev-1"]
    check = check_evidence_pit(view, ctx.as_of)
    assert not check.passed
    assert check.level == "FATAL"


def test_evidence_ids_exist_dangling(ctx) -> None:
    view = _macro_scaffold(ctx.as_of)
    view.liquidity = DimensionView(
        direction="stable",
        score=0.0,
        note="x",
        evidence_refs=["missing-id"],
    )
    check = check_evidence_ids_exist(view)
    assert not check.passed
    assert "missing-id" in check.detail


def test_figures_traceable_from_evidence_excerpt(ctx) -> None:
    view = _macro_scaffold(ctx.as_of)
    trace = AgentTrace(agent_name="macro")
    check = check_figures_traceable(view, trace)
    assert check.passed, check.detail


def test_figures_untraceable_warn(ctx) -> None:
    view = _macro_scaffold(ctx.as_of)
    view.regime_drivers = ["神秘涨幅 +99.99%"]
    trace = AgentTrace(agent_name="macro")
    check = check_figures_traceable(view, trace)
    assert not check.passed
    assert check.level == "WARN"


def test_tool_registry_records_into_bound_trace(ctx) -> None:
    reg = ToolRegistry()

    def fake(*, query: str, as_of: date, top_k: int = 3) -> dict[str, float]:
        return {"ret": 0.015, "n": 42}

    reg.register("search_knowledge", fake)
    trace = AgentTrace(agent_name="macro")
    with bind_trace(trace):
        out = reg.call("search_knowledge", {"query": "宏观"}, ctx)
    assert out["ret"] == 0.015
    assert len(trace.tool_calls) == 1
    assert "as_of" not in trace.tool_calls[0].args
    assert trace.tool_calls[0].result["n"] == 42


@pytest.mark.asyncio
async def test_validate_agent_output_ok_for_heuristic_macro(facts, ctx) -> None:
    view = await MacroAgent(facts).run(ctx)
    trace = AgentTrace(agent_name="macro")
    trace.add_context("research_facts", facts.model_dump(mode="json"))
    result = validate_agent_output(view, ctx, trace, agent_name="macro")
    assert result.ok
    assert result.untraceable_figure_count == 0


@pytest.mark.asyncio
async def test_orchestrator_runs_validation(facts) -> None:
    orch = Orchestrator(max_stocks=5, max_industries=2, max_themes=1, max_concurrency=2)
    result = await orch.run_daily(facts.as_of, facts.market, facts)
    assert not result.aborted
    assert result.brief is not None
    assert result.validations
    assert result.validation_fatal_count == 0
    # Heuristic outputs should keep untraceable figures near zero when facts are seeded.
    assert result.untraceable_figure_count <= 3


@pytest.mark.asyncio
async def test_orchestrator_skips_stock_on_validation_fatal(facts, ctx) -> None:
    from quantagent.agents.stock.agent import StockAgent

    class BadStock(StockAgent):
        async def run(self, ctx: AgentContext):
            view = await super().run(ctx)
            # Break evidence refs after heuristic build.
            view.bull_points[0].evidence_refs = ["does-not-exist"]
            return view

    orch = Orchestrator(max_stocks=1, max_industries=1, max_themes=0, max_concurrency=1)
    # Patch stock path by running bounded with a bad agent
    seed = facts.stocks[0]
    views, skipped = await orch._run_bounded([BadStock(seed)], ctx)  # noqa: SLF001
    assert views == []
    assert seed.symbol in skipped
    assert any(v.has_fatal for v in orch.validations)
