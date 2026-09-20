"""MacroAgent — market regime view (deterministic skeleton)."""

from __future__ import annotations

from typing import Literal

from quantagent.agents._heuristic import evidence
from quantagent.agents.base import AgentContext
from quantagent.agents.schemas.views import (
    DimensionView,
    MacroView,
    SectorImpact,
)
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.research_facts import ResearchFacts
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import AgentError


class MacroAgent:
    """Skeleton MacroAgent: heuristic regime from ResearchFacts (+ optional RAG)."""

    name = "macro"
    tier = "medium"

    def __init__(
        self,
        facts: ResearchFacts,
        *,
        tools: ToolRegistry | None = None,
        force_fail: bool = False,
    ) -> None:
        self._facts = facts
        self._tools = tools
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> MacroView:
        if self._force_fail:
            raise AgentError("macro agent forced failure")
        facts = self._facts
        ret = facts.index_return_1d
        breadth = facts.n_up - facts.n_down

        regime: Literal["risk_on", "risk_off", "neutral", "transition"]
        if ret <= -0.015 or breadth < -200:
            regime = "risk_off"
            confidence = 0.65
        elif ret >= 0.015 or breadth > 200:
            regime = "risk_on"
            confidence = 0.65
        elif abs(ret) < 0.003:
            regime = "neutral"
            confidence = 0.55
        else:
            regime = "transition"
            confidence = 0.5

        rag_note = ""
        if self._tools is not None and "search_knowledge" in self._tools.names():
            try:
                hits = self._tools.call(
                    "search_knowledge",
                    {"query": "宏观 政策 流动性 风险偏好", "top_k": 3},
                    ctx,
                )
                if hits:
                    rag_note = f"；知识库命中 {len(hits)} 条"
            except Exception:  # noqa: BLE001 — soft-fail RAG in skeleton
                rag_note = "；知识库检索不可用"

        ev = [
            evidence(
                "ev-macro-index",
                kind="price",
                ref_id=f"index:{facts.as_of.isoformat()}",
                excerpt=f"index_return_1d={ret:+.4f} up={facts.n_up} down={facts.n_down}",
                as_of=ctx.as_of,
            ),
            evidence(
                "ev-macro-note",
                kind="quality",
                ref_id=f"macro-note:{ctx.run_id}",
                excerpt=(facts.macro_note + rag_note)[:400],
                as_of=ctx.as_of,
            ),
        ]

        def _dim(
            direction: Literal["improving", "deteriorating", "stable", "unclear"],
            score: float,
            note: str,
        ) -> DimensionView:
            return DimensionView(
                direction=direction,
                score=score,
                note=note[:200],
                evidence_refs=["ev-macro-index"],
            )

        impacts: list[SectorImpact] = []
        for seed in facts.industries[:3]:
            impacts.append(
                SectorImpact(
                    industry_code=seed.code,
                    impact=max(-1.0, min(1.0, seed.ret_1d * 5.0)),
                    reason=f"近端收益 {seed.ret_1d:+.2%}",
                    confidence=0.4,
                )
            )

        view = MacroView(
            as_of=ctx.as_of,
            regime=regime,
            regime_confidence=confidence,
            regime_drivers=[
                f"指数日收益 {ret:+.2%}",
                f"涨跌家数差 {breadth}",
            ],
            liquidity=_dim("stable", 0.0, "骨架：未接宏观序列，流动性标为稳定"),
            growth=_dim("unclear", 0.0, "骨架：增长维度数据不足"),
            inflation=_dim("unclear", 0.0, "骨架：通胀维度数据不足"),
            policy=_dim("stable", 0.0, "骨架：政策维度待接政策新闻工具"),
            external=_dim("unclear", 0.0, "骨架：外部环境数据不足"),
            sector_impacts=impacts,
            upcoming_events=[],
            evidence=ev,
        )
        require_evidence(view.evidence, min_count=1)
        return validate_model(view)  # type: ignore[return-value]


def neutral_macro_view(ctx: AgentContext, *, reason: str) -> MacroView:
    """Degraded fallback when MacroAgent fails after retry."""
    ev = evidence(
        "ev-macro-degraded",
        kind="quality",
        ref_id=f"macro-degraded:{ctx.run_id}",
        excerpt=reason[:400],
        as_of=ctx.as_of,
    )
    unclear = DimensionView(
        direction="unclear",
        score=0.0,
        note="宏观 Agent 失败，使用中性降级",
        evidence_refs=["ev-macro-degraded"],
    )
    view = MacroView(
        as_of=ctx.as_of,
        regime="neutral",
        regime_confidence=0.2,
        regime_drivers=["宏观 Agent 失败，降级为中性 regime"],
        liquidity=unclear,
        growth=unclear,
        inflation=unclear,
        policy=unclear,
        external=unclear,
        sector_impacts=[],
        upcoming_events=[],
        evidence=[ev],
        degraded=True,
        degrade_reason=reason[:300],
    )
    return validate_model(view)  # type: ignore[return-value]
