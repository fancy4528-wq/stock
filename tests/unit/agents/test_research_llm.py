"""Research Agents LLM path: complete_with_budget + heuristic fallback."""

from __future__ import annotations

import json
from datetime import date

import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.fixtures import sample_research_facts
from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.client import EchoLLMClient, NullLLMClient
from quantagent.agents.llm.config import BudgetConfig, LLMConfig, TierConfig
from quantagent.agents.llm.metering import CostTracker
from quantagent.agents.llm.structured import (
    ResearchLlmBundle,
    complete_research_model,
    extract_json_object,
)
from quantagent.agents.macro.agent import MacroAgent
from quantagent.agents.orchestrator import Orchestrator
from quantagent.agents.schemas.views import MacroView
from quantagent.agents.tools import build_default_tool_registry
from quantagent.shared.errors import SchemaValidationError


def _llm_cfg(*, research: float = 10.0) -> LLMConfig:
    tiers = {
        "small": TierConfig(
            provider="openai_compatible",
            model="echo-small",
            base_url="http://localhost",
            max_tokens_out=256,
            temperature=0.0,
            input_usd_per_1m=0.1,
            output_usd_per_1m=0.2,
        ),
        "medium": TierConfig(
            provider="openai_compatible",
            model="echo-medium",
            base_url="http://localhost",
            max_tokens_out=1024,
            temperature=0.0,
            input_usd_per_1m=0.1,
            output_usd_per_1m=0.2,
        ),
        "large": TierConfig(
            provider="openai_compatible",
            model="echo-large",
            base_url="http://localhost",
            max_tokens_out=2048,
            temperature=0.0,
            input_usd_per_1m=0.1,
            output_usd_per_1m=0.2,
        ),
    }
    budget = BudgetConfig(
        daily_usd_limit=research + 1.0,
        monthly_usd_limit=100.0,
        allocations={
            "daily_research": research,
            "monitoring": 0.3,
            "news_extraction": 0.3,
            "adhoc": 0.1,
        },
        on_exceed={
            "daily_research": "degrade",
            "monitoring": "l1_only",
            "news_extraction": "skip",
            "adhoc": "abort",
        },
        per_call_max_tokens_in=30000,
        per_call_max_tokens_out=4000,
    )
    return LLMConfig(tiers=tiers, budget=budget)


def test_extract_json_object_fence() -> None:
    data = extract_json_object('```json\n{"a": 1}\n```')
    assert data == {"a": 1}


def test_extract_json_object_rejects_non_object() -> None:
    with pytest.raises(SchemaValidationError):
        extract_json_object("[1, 2]")


@pytest.mark.asyncio
async def test_macro_null_llm_stays_heuristic() -> None:
    facts = sample_research_facts(date(2026, 9, 12))
    bundle = ResearchLlmBundle(
        llm=NullLLMClient(),
        budget=TokenBudget(llm_config=_llm_cfg()),
        costs=CostTracker(),
    )
    agent = MacroAgent(facts, llm=bundle)
    ctx = AgentContext(
        as_of=facts.as_of, market="CN", run_id="t-null", token_budget_usd=1.0
    )
    view = await agent.run(ctx)
    assert isinstance(view, MacroView)
    assert bundle.costs.total_usd == 0.0


@pytest.mark.asyncio
async def test_macro_echo_llm_refines_regime() -> None:
    facts = sample_research_facts(date(2026, 9, 12))
    agent_probe = MacroAgent(facts)
    ctx = AgentContext(
        as_of=facts.as_of, market="CN", run_id="t-echo", token_budget_usd=1.0
    )
    scaffold = await agent_probe.run(ctx)
    payload = scaffold.model_dump(mode="json")
    payload["regime"] = "risk_off"
    payload["regime_drivers"] = ["LLM echo override"]
    echo = EchoLLMClient(json.dumps(payload, ensure_ascii=False))
    bundle = ResearchLlmBundle(
        llm=echo,
        budget=TokenBudget(llm_config=_llm_cfg()),
        costs=CostTracker(),
    )
    agent = MacroAgent(facts, llm=bundle)
    view = await agent.run(ctx)
    assert view.regime == "risk_off"
    assert view.regime_drivers == ["LLM echo override"]
    assert any(r.mode == "llm" for r in bundle.costs.records)


@pytest.mark.asyncio
async def test_complete_research_model_budget_skip_returns_none() -> None:
    cfg = _llm_cfg(research=0.00001)
    bundle = ResearchLlmBundle(
        llm=EchoLLMClient('{"regime":"neutral"}'),
        budget=TokenBudget(llm_config=cfg),
        costs=CostTracker(),
    )
    out = await complete_research_model(
        bundle,
        agent="macro",
        tier="medium",
        prompt_name="macro",
        user_payload={"x": 1},
        run_id="budget-test",
        model_cls=MacroView,
    )
    assert out is None
    assert bundle.degradations or any(r.mode == "budget_skip" for r in bundle.costs.records)


@pytest.mark.asyncio
async def test_orchestrator_with_echo_llm() -> None:
    facts = sample_research_facts(date(2026, 9, 12))
    # Echo returns non-view JSON → agents fall back to heuristic after schema fail.
    bundle = ResearchLlmBundle(
        llm=EchoLLMClient('{"not":"a_view"}'),
        budget=TokenBudget(llm_config=_llm_cfg()),
        costs=CostTracker(),
    )
    tools = build_default_tool_registry(include_knowledge=False, include_db=False)
    orch = Orchestrator(tools=tools, max_stocks=5, max_industries=2, llm=bundle)
    result = await orch.run_daily(facts.as_of, facts.market, facts)
    assert not result.aborted
    assert result.brief is not None
    assert result.brief.regime in {"risk_on", "risk_off", "neutral", "transition"}
    assert result.llm_cost_usd >= 0.0


@pytest.mark.asyncio
async def test_chief_echo_llm_merges_refine_patch() -> None:
    """Chief LLM path must accept slim ChiefRefinePatch, not full MarketBrief."""
    from quantagent.agents.chief.agent import ChiefAgent
    from quantagent.agents.sector.industry import IndustryAgent
    from quantagent.agents.stock.agent import StockAgent

    facts = sample_research_facts(date(2026, 9, 12))
    ctx = AgentContext(
        as_of=facts.as_of, market="CN", run_id="t-chief-patch", token_budget_usd=1.0
    )
    macro = await MacroAgent(facts).run(ctx)
    sector = await IndustryAgent(facts.industries[0]).run(ctx)
    stock = await StockAgent(facts.stocks[0]).run(ctx)
    upstream_ctx = ctx.model_copy(
        update={"upstream": {"macro": macro, "sectors": [sector], "stocks": [stock]}}
    )

    patch = {
        "market_summary": "LLM chief summary override for truncation fix",
        "regime_note": "LLM regime note",
        "allocation_stance": {
            "equity_stance": "defensive",
            "rationale": "echo patch rationale",
            "preferred_sectors": [sector.sector_code],
            "avoid_sectors": [],
        },
        "disagreements": [],
        "key_uncertainties": ["echo uncertainty"],
        "watchlist": [
            {
                "sector_code": sector.sector_code,
                "reason": "echo watch",
                "trigger": "unit test",
            }
        ],
    }
    bundle = ResearchLlmBundle(
        llm=EchoLLMClient(json.dumps(patch, ensure_ascii=False)),
        budget=TokenBudget(llm_config=_llm_cfg()),
        costs=CostTracker(),
    )
    brief = await ChiefAgent(llm=bundle).run(upstream_ctx)
    assert brief.market_summary == patch["market_summary"]
    assert brief.regime_note == "LLM regime note"
    assert brief.allocation_stance.equity_stance == "defensive"
    assert brief.key_uncertainties == ["echo uncertainty"]
    # Ranking / evidence / regime remain heuristic-owned
    assert brief.regime == macro.regime
    assert brief.sector_ranking
    assert brief.evidence
    assert any(r.mode == "llm" for r in bundle.costs.records)
