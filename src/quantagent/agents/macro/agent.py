"""MacroAgent — market regime view (heuristic + optional DB tools + LLM)."""

from __future__ import annotations

from typing import Any, Literal

from quantagent.agents._heuristic import evidence
from quantagent.agents.base import AgentContext
from quantagent.agents.llm.structured import ResearchLlmBundle, complete_research_model
from quantagent.agents.macro.shocks import (
    assess_market_shocks,
    external_from_shocks,
    items_from_payload,
    regime_after_shocks,
)
from quantagent.agents.schemas.views import (
    DimensionView,
    MacroView,
    SectorImpact,
)
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.research_facts import ResearchFacts
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
    except Exception:  # noqa: BLE001 — soft-fail individual tools
        return None


class MacroAgent:
    """MacroAgent: regime from ResearchFacts, enriched by DB tools / LLM when present."""

    name = "macro"
    tier = "medium"

    def __init__(
        self,
        facts: ResearchFacts,
        *,
        tools: ToolRegistry | None = None,
        llm: ResearchLlmBundle | None = None,
        force_fail: bool = False,
    ) -> None:
        self._facts = facts
        self._tools = tools
        self._llm = llm
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> MacroView:
        if self._force_fail:
            raise AgentError("macro agent forced failure")
        heuristic = self._build_heuristic(ctx)
        if self._llm is None or not self._llm.enabled():
            return heuristic

        payload = {
            "scaffold": heuristic.model_dump(mode="json"),
            "facts": {
                "index_return_1d": self._facts.index_return_1d,
                "n_up": self._facts.n_up,
                "n_down": self._facts.n_down,
                "macro_note": self._facts.macro_note,
                "market_shocks": [
                    d for d in heuristic.regime_drivers if d.startswith("市场冲击[")
                ],
            },
        }
        inject = {
            "as_of": ctx.as_of.isoformat(),
            "evidence": [e.model_dump(mode="json") for e in heuristic.evidence],
        }
        refined = await complete_research_model(
            self._llm,
            agent=self.name,
            tier=self.tier,
            prompt_name="macro",
            user_payload=payload,
            run_id=ctx.run_id,
            model_cls=MacroView,
            inject=inject,
            repair_hint="retry",
            user_prefix=(
                "在 scaffold MacroView 基础上 refinement（regime / drivers / dimension notes）；"
                "保留 evidence_refs 指向已有 evidence；不要编造数字；仅输出 JSON：\n"
            ),
        )
        if refined is None:
            return heuristic
        require_evidence(refined.evidence, min_count=1)
        # A critical shock is a hard floor. The model may rewrite notes, not the stance.
        return _overlay_shocks(validate_model(refined), heuristic)  # type: ignore[return-value]

    def _build_heuristic(self, ctx: AgentContext) -> MacroView:
        facts = self._facts
        ret = facts.index_return_1d
        n_up, n_down = facts.n_up, facts.n_down

        breadth_payload = _tool_call(
            self._tools,
            "get_market_breadth",
            {"lookback_days": 20},
            ctx,
        )
        if isinstance(breadth_payload, dict) and breadth_payload.get("available"):
            today = breadth_payload.get("today") or {}
            if isinstance(today, dict) and today.get("n_up") is not None:
                n_up = int(today["n_up"])
                n_down = int(today.get("n_down") or 0)

        index_payload = _tool_call(
            self._tools,
            "get_index_prices",
            {"lookback_days": 5},
            ctx,
        )
        if isinstance(index_payload, dict) and index_payload.get("rows"):
            rows = index_payload["rows"]
            if len(rows) >= 2:
                try:
                    c0 = float(rows[-2]["close"])
                    c1 = float(rows[-1]["close"])
                    if c0:
                        ret = c1 / c0 - 1.0
                except (KeyError, TypeError, ValueError):
                    pass

        breadth = n_up - n_down
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
        hits = _tool_call(
            self._tools,
            "search_knowledge",
            {"query": "宏观 政策 流动性 风险偏好", "top_k": 3},
            ctx,
        )
        if hits:
            rag_note = f"；知识库命中 {len(hits)} 条"

        policy_payload = _tool_call(
            self._tools,
            "get_policy_news",
            {"lookback_days": 14, "limit": 10},
            ctx,
        )
        policy_n = 0
        if isinstance(policy_payload, dict) and policy_payload.get("available"):
            policy_n = len(policy_payload.get("events") or []) + len(
                policy_payload.get("news") or []
            )

        if policy_n >= 3:
            policy_dim = DimensionView(
                direction="improving",
                score=0.2,
                note=f"近端政策/监管相关条目 {policy_n} 条",
                evidence_refs=["ev-macro-policy"],
            )
        elif policy_n == 0:
            policy_dim = DimensionView(
                direction="stable",
                score=0.0,
                note="未检索到政策类新闻（或工具不可用）",
                evidence_refs=["ev-macro-index"],
            )
        else:
            policy_dim = DimensionView(
                direction="stable",
                score=0.1,
                note=f"少量政策相关条目 {policy_n} 条",
                evidence_refs=["ev-macro-policy"],
            )

        shock_payload = _tool_call(
            self._tools,
            "get_market_shocks",
            {"lookback_hours": 36, "limit": 300},
            ctx,
        )
        shocks = assess_market_shocks(
            items_from_payload(shock_payload if isinstance(shock_payload, dict) else None),
            as_of=ctx.as_of,
        )
        drivers = [
            f"指数日收益 {ret:+.2%}",
            f"涨跌家数差 {breadth}",
        ]
        regime, confidence, drivers = regime_after_shocks(regime, confidence, drivers, shocks)

        ev = [
            evidence(
                "ev-macro-index",
                kind="price",
                ref_id=f"index:{facts.as_of.isoformat()}",
                excerpt=f"index_return_1d={ret:+.4f} up={n_up} down={n_down} breadth={breadth}",
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
        if policy_n:
            ev.append(
                evidence(
                    "ev-macro-policy",
                    kind="news",
                    ref_id=f"policy:{ctx.as_of.isoformat()}",
                    excerpt=f"policy-related items={policy_n}",
                    as_of=ctx.as_of,
                )
            )
        external_spec = external_from_shocks(shocks)
        if external_spec is not None:
            ev.append(
                evidence(
                    "ev-macro-shock",
                    kind="news",
                    ref_id=f"shock:{ctx.as_of.isoformat()}",
                    excerpt=external_spec[2][:400],
                    as_of=ctx.as_of,
                )
            )

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

        macro_stub = _tool_call(
            self._tools, "get_macro_series", {"series_ids": ["cpi"], "lookback_months": 6}, ctx
        )
        if isinstance(macro_stub, dict) and not macro_stub.get("available"):
            growth_note = "增长维度：宏观序列表未迁移"
        else:
            growth_note = "增长维度数据不足"

        if external_spec is None:
            external = _dim("unclear", 0.0, "外部环境数据不足")
        else:
            direction, score, note = external_spec
            external = DimensionView(
                direction=direction,  # type: ignore[arg-type]
                score=score,
                note=note[:200],
                evidence_refs=["ev-macro-shock"],
            )

        view = MacroView(
            as_of=ctx.as_of,
            regime=regime,
            regime_confidence=confidence,
            regime_drivers=drivers,
            liquidity=_dim("stable", 0.0, "流动性：北向/资金流表未迁移，标为稳定"),
            growth=_dim("unclear", 0.0, growth_note),
            inflation=_dim("unclear", 0.0, "通胀维度依赖宏观序列（未迁移）"),
            policy=policy_dim,
            external=external,
            sector_impacts=impacts,
            upcoming_events=[],
            evidence=ev,
        )
        require_evidence(view.evidence, min_count=1)
        return validate_model(view)  # type: ignore[return-value]


def _overlay_shocks(refined: MacroView, heuristic: MacroView) -> MacroView:
    """Keep a shock-driven regime if the heuristic already set one."""
    shock_drivers = [d for d in heuristic.regime_drivers if d.startswith("市场冲击[")]
    if not shock_drivers:
        return refined
    drivers = [d for d in refined.regime_drivers if not d.startswith("市场冲击[")]
    kept = [e for e in refined.evidence if e.evidence_id != "ev-macro-shock"]
    shock_ev = [e for e in heuristic.evidence if e.evidence_id == "ev-macro-shock"]
    regime = refined.regime
    confidence = refined.regime_confidence
    if heuristic.external.score <= -0.6:
        regime = "risk_off"
        confidence = max(confidence, heuristic.regime_confidence)
    elif regime == "risk_on" and heuristic.regime != "risk_on":
        regime = heuristic.regime
        confidence = min(confidence, heuristic.regime_confidence)
    return refined.model_copy(
        update={
            "regime": regime,
            "regime_confidence": confidence,
            "regime_drivers": [*shock_drivers, *drivers][:6],
            "external": heuristic.external,
            "evidence": [*kept, *shock_ev],
        }
    )


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
