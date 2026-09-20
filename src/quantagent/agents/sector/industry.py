"""IndustryAgent / ThemeAgent — SectorView producers (+ optional DB tools)."""

from __future__ import annotations

from typing import Any, Literal

from quantagent.agents._heuristic import evidence, point, risk, score_from_return
from quantagent.agents.base import AgentContext
from quantagent.agents.llm.structured import ResearchLlmBundle, complete_research_model
from quantagent.agents.schemas.views import (
    SectorDimensions,
    SectorView,
    StockCandidate,
    ThemeLifecycle,
)
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.research_facts import SectorSeed
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import AgentError


def _tool_call(
    tools: ToolRegistry | None,
    name: str,
    args: dict[str, Any],
    ctx: AgentContext,
) -> Any | None:
    if tools is None or name not in tools.names():
        return None
    try:
        return tools.call(name, args, ctx)
    except Exception:  # noqa: BLE001
        return None


def _sector_dimensions(
    seed: SectorSeed,
    score: float,
    *,
    news_n: int,
) -> SectorDimensions:
    from quantagent.agents._heuristic import dim

    mom = score_from_return(seed.ret_20d)
    day_score = score_from_return(seed.ret_1d)
    news_score = 0.55 if news_n else day_score
    return SectorDimensions(
        fundamental=dim(0.5, "基本面汇总工具未接（待板块财务）"),
        valuation=dim(0.5, "板块估值分位工具未接"),
        momentum=dim(mom, f"ret_20d={seed.ret_20d:+.2%}", ["ev-sector-ret"]),
        flow=dim(0.5, "资金流表未迁移"),
        news_sentiment=dim(
            news_score,
            f"ret_1d={seed.ret_1d:+.2%}；近端事件 {news_n} 条",
            ["ev-sector-ret"] if not news_n else ["ev-sector-news"],
        ),
        macro_fit=dim(score, "与粗筛动量对齐", ["ev-sector-ret"]),
    )


def _build_sector_view(
    ctx: AgentContext,
    *,
    seed: SectorSeed,
    sector_type: Literal["industry", "theme"],
    horizon: Literal["1w", "1m", "3m", "6m"],
    lifecycle: ThemeLifecycle | None = None,
    tools: ToolRegistry | None = None,
) -> SectorView:
    score = score_from_return(0.6 * seed.ret_20d + 0.4 * seed.ret_1d)
    conf = 0.45 if abs(seed.ret_20d) < 0.02 else 0.6

    news_n = 0
    proxy_note = ""
    if sector_type == "industry":
        news_payload = _tool_call(
            tools,
            "get_sector_news",
            {"sector_code": seed.code, "lookback_days": 14, "limit": 10},
            ctx,
        )
        if isinstance(news_payload, dict) and news_payload.get("available"):
            news_n = len(news_payload.get("rows") or [])
        prices_payload = _tool_call(
            tools,
            "get_sector_prices",
            {"sector_code": seed.code, "lookback_days": 40},
            ctx,
        )
        if isinstance(prices_payload, dict) and prices_payload.get("available"):
            n_names = int(prices_payload.get("n_names") or 0)
            proxy_note = f"；等权成分代理 n={n_names}"
            if n_names:
                conf = min(0.75, conf + 0.05)

    ev = [
        evidence(
            "ev-sector-ret",
            kind="sector",
            ref_id=f"sector:{seed.code}:{ctx.as_of.isoformat()}",
            excerpt=f"{seed.code} ret_1d={seed.ret_1d:+.4f} ret_20d={seed.ret_20d:+.4f}",
            as_of=ctx.as_of,
        ),
        evidence(
            "ev-sector-meta",
            kind="quality",
            ref_id=f"sector-meta:{seed.code}:{ctx.run_id}",
            excerpt=f"type={sector_type} name={seed.name}{proxy_note}",
            as_of=ctx.as_of,
        ),
    ]
    if news_n:
        ev.append(
            evidence(
                "ev-sector-news",
                kind="news",
                ref_id=f"sector-news:{seed.code}",
                excerpt=f"related events={news_n}",
                as_of=ctx.as_of,
            )
        )

    candidates = [
        StockCandidate(
            symbol=c.symbol,
            name=c.name,
            role=c.role,
            preliminary_score=c.preliminary_score,
            reason=f"粗筛候选，板块 {seed.code}",
        )
        for c in seed.candidates[:10]
    ]
    bull = point(
        f"{seed.name} 近端动量 {seed.ret_1d:+.2%} / 20日 {seed.ret_20d:+.2%}",
        "moderate" if seed.ret_1d >= 0 else "weak",
        ["ev-sector-ret"],
    )
    bear = point(
        f"{seed.name} 存在动量回撤与政策/估值不确定性",
        "moderate",
        ["ev-sector-meta"],
    )
    thesis = (
        f"数据显示 {seed.name}（{seed.code}）近端收益 "
        f"{seed.ret_1d:+.2%}，20 日 {seed.ret_20d:+.2%}"
        f"{proxy_note}。"
    )
    if news_n:
        thesis += f"近端关联事件 {news_n} 条。"
    else:
        thesis += "新闻面偏静或未检索到关联事件。"

    view = SectorView(
        as_of=ctx.as_of,
        sector_type=sector_type,
        sector_code=seed.code,
        sector_name=seed.name,
        score=score,
        confidence=conf,
        horizon=horizon,
        thesis=thesis[:800],
        dimensions=_sector_dimensions(seed, score, news_n=news_n),
        bull_points=[bull],
        bear_points=[bear],
        key_uncertainties=["板块财务汇总与资金流尚未完整接入"],
        candidates=candidates,
        risks=[risk(f"{seed.name} 短期波动与流动性风险")],
        theme_lifecycle=lifecycle,
        evidence=ev,
    )
    require_evidence(view.evidence, min_count=2)
    return validate_model(view)  # type: ignore[return-value]


async def _maybe_refine_sector(
    ctx: AgentContext,
    heuristic: SectorView,
    *,
    llm: ResearchLlmBundle | None,
    agent_name: str,
    prompt_name: str,
    tier: str,
) -> SectorView:
    if llm is None or not llm.enabled():
        return heuristic
    inject = {
        "as_of": ctx.as_of.isoformat(),
        "sector_type": heuristic.sector_type,
        "sector_code": heuristic.sector_code,
        "sector_name": heuristic.sector_name,
        "evidence": [e.model_dump(mode="json") for e in heuristic.evidence],
        "candidates": [c.model_dump(mode="json") for c in heuristic.candidates],
    }
    refined = await complete_research_model(
        llm,
        agent=agent_name,
        tier=tier,
        prompt_name=prompt_name,
        user_payload={"scaffold": heuristic.model_dump(mode="json")},
        run_id=ctx.run_id,
        model_cls=SectorView,
        inject=inject,
        repair_hint="retry",
        user_prefix=(
            "在 scaffold SectorView 基础上 refinement（thesis / bull/bear / uncertainties）；"
            "保留 evidence_refs 与 candidates；不要编造数字；仅输出 JSON：\n"
        ),
    )
    if refined is None:
        return heuristic
    require_evidence(refined.evidence, min_count=2)
    return validate_model(refined)  # type: ignore[return-value]


class IndustryAgent:
    name = "industry"
    tier = "medium"

    def __init__(
        self,
        seed: SectorSeed,
        *,
        tools: ToolRegistry | None = None,
        llm: ResearchLlmBundle | None = None,
        force_fail: bool = False,
    ) -> None:
        self._seed = seed
        self._tools = tools
        self._llm = llm
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> SectorView:
        if self._force_fail:
            raise AgentError(f"industry agent forced failure: {self._seed.code}")
        heuristic = _build_sector_view(
            ctx,
            seed=self._seed,
            sector_type="industry",
            horizon="3m",
            tools=self._tools,
        )
        return await _maybe_refine_sector(
            ctx,
            heuristic,
            llm=self._llm,
            agent_name=self.name,
            prompt_name="industry",
            tier=self.tier,
        )


class ThemeAgent:
    name = "theme"
    tier = "medium"

    def __init__(
        self,
        seed: SectorSeed,
        *,
        tools: ToolRegistry | None = None,
        llm: ResearchLlmBundle | None = None,
        force_fail: bool = False,
    ) -> None:
        self._seed = seed
        self._tools = tools
        self._llm = llm
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> SectorView:
        if self._force_fail:
            raise AgentError(f"theme agent forced failure: {self._seed.code}")
        stage: Literal["emerging", "acceleration", "peak", "declining", "dormant"]
        if self._seed.ret_1d >= 0.03 and self._seed.ret_20d >= 0.05:
            stage = "acceleration"
            days = 10
        elif self._seed.ret_20d <= -0.05:
            stage = "declining"
            days = 20
        else:
            stage = "emerging"
            days = 5
        lifecycle = ThemeLifecycle(
            stage=stage,
            days_since_activation=days,
            evidence=f"ret_1d={self._seed.ret_1d:+.2%} ret_20d={self._seed.ret_20d:+.2%}",
        )
        heuristic = _build_sector_view(
            ctx,
            seed=self._seed,
            sector_type="theme",
            horizon="1m",
            lifecycle=lifecycle,
            tools=self._tools,
        )
        return await _maybe_refine_sector(
            ctx,
            heuristic,
            llm=self._llm,
            agent_name=self.name,
            prompt_name="theme",
            tier=self.tier,
        )
