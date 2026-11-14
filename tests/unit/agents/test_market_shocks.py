"""Market shocks move the macro stance and leave position weights alone."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.chief.agent import _stance_rationale
from quantagent.agents.fixtures import sample_research_facts
from quantagent.agents.macro.agent import MacroAgent, _overlay_shocks
from quantagent.agents.macro.shocks import assess_market_shocks
from quantagent.agents.tools.dispatch import ToolRegistry

CN = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 9, 12)


def _at(hour: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=CN)


def test_same_day_war_is_one_critical_shock() -> None:
    assessment = assess_market_shocks(
        [
            ("中东军事冲突升级", _at(10)),
            ("军事冲突持续", _at(14)),
            ("行业价格战加剧", _at(11)),
            ("茅台董事会换届选举", _at(11)),
        ],
        as_of=DAY,
    )
    assert [s.keyword for s in assessment.active] == ["军事冲突"]
    assert assessment.critical_negative
    assert assessment.stance_line is not None
    assert "建议偏向防守" in assessment.stance_line
    assert "不改变仓位" in assessment.stance_line


def test_preopen_carry_uses_monitor_cooldown() -> None:
    previous = date(2026, 9, 11)
    kept = assess_market_shocks(
        [("中东军事冲突升级", datetime(previous.year, previous.month, previous.day, 22, 30, tzinfo=CN))],
        as_of=DAY,
    )
    dropped = assess_market_shocks(
        [("中东军事冲突升级", datetime(previous.year, previous.month, previous.day, 20, 0, tzinfo=CN))],
        as_of=DAY,
    )
    assert kept.active and kept.active[0].keyword == "军事冲突"
    assert dropped.active == []


def test_election_does_not_force_defense() -> None:
    assessment = assess_market_shocks(
        [("美国总统选举进入计票", _at(10))],
        as_of=DAY,
    )
    assert assessment.active[0].direction == "unclear"
    assert assessment.critical_negative == []
    assert assessment.stance_line is not None
    assert "方向不明" in assessment.stance_line
    assert "偏向防守" not in assessment.stance_line


def _tool(items: list[dict[str, str]]) -> ToolRegistry:
    reg = ToolRegistry()

    def get_market_shocks(*, as_of: date | None = None, lookback_hours: int = 36, limit: int = 80):  # noqa: ARG001
        return {"available": True, "items": items}

    reg.register("get_market_shocks", get_market_shocks)
    return reg


@pytest.mark.asyncio
async def test_critical_shock_overrides_price_risk_on() -> None:
    facts = sample_research_facts(DAY)
    ctx = AgentContext(as_of=DAY, market="CN", run_id="shock-war")
    view = await MacroAgent(
        facts,
        tools=_tool(
            [{"title": "中东军事冲突升级", "published_at": "2026-09-12T10:00:00+08:00"}]
        ),
    ).run(ctx)
    assert view.regime == "risk_off"
    assert view.external.direction == "deteriorating"
    assert view.external.score <= -0.6
    assert any(d.startswith("市场冲击[军事冲突]") for d in view.regime_drivers)
    rationale = _stance_rationale(view, "defensive")
    assert "不改变仓位" in rationale
    assert "军事冲突" in rationale
    flipped = view.model_copy(
        update={"regime": "risk_on", "regime_drivers": ["指数日收益 +1.00%"]}
    )
    assert _overlay_shocks(flipped, view).regime == "risk_off"


@pytest.mark.asyncio
async def test_high_shock_downgrades_risk_on_only() -> None:
    facts = sample_research_facts(DAY)
    ctx = AgentContext(as_of=DAY, market="CN", run_id="shock-sanction")
    view = await MacroAgent(
        facts,
        tools=_tool([{"title": "美国宣布新一轮制裁", "published_at": "2026-09-12T10:00:00+08:00"}]),
    ).run(ctx)
    assert view.regime == "neutral"
    assert view.external.score == -0.4


@pytest.mark.asyncio
async def test_no_shock_keeps_price_regime() -> None:
    facts = sample_research_facts(DAY)
    ctx = AgentContext(as_of=DAY, market="CN", run_id="shock-none")
    view = await MacroAgent(facts, tools=_tool([])).run(ctx)
    assert view.regime == "risk_on"
    assert "外部环境数据不足" in view.external.note
