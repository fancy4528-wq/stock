"""L3 deep analysis — reuse StockAgent for deep-flagged hits (P2b).

Only runs when L2 (or critical news/ann) requests deep analysis. Hard-capped by
``MonitorBudget.reserve_l3`` (default ≤ 10/day). Uses the ``monitoring``
TokenBudget pool — never borrows from ``daily_research``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from quantagent.agents.base import AgentContext
from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.client import LLMClient
from quantagent.agents.llm.factory import build_llm_client
from quantagent.agents.llm.metering import CostTracker
from quantagent.agents.llm.structured import ResearchLlmBundle, llm_enabled
from quantagent.agents.schemas.views import StockView
from quantagent.agents.stock.agent import StockAgent
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.research_facts import StockSeed
from quantagent.monitor.budget import MonitorBudget
from quantagent.monitor.types import TriggerHit

logger = logging.getLogger(__name__)

L3Mode = Literal["llm", "heuristic", "skipped", "disabled"]


@dataclass
class L3Stats:
    candidates: int = 0
    analyzed: int = 0
    skipped_cap: int = 0
    skipped_error: int = 0
    cost_usd: float = 0.0
    mode: L3Mode = "disabled"
    note: str | None = None
    symbols: list[str] = field(default_factory=list)


def needs_l3(hit: TriggerHit) -> bool:
    """True when the hit should be upgraded via StockAgent."""
    if hit.analysis_level == "L3":
        return False
    ev = hit.evidence or {}
    if ev.get("needs_deep_analysis") or ev.get("l2_deep"):
        return True
    code = hit.code.split("/")[0]
    # Critical news/ann that never got an L2 deep flag (e.g. ANN path).
    if hit.severity == "critical" and code.startswith(("NEWS_", "ANN_")):
        return True
    return False


def _seed_from_hit(
    hit: TriggerHit,
    *,
    name_by_symbol: dict[str, str],
    industry_by_symbol: dict[str, str] | None = None,
) -> StockSeed:
    industries = industry_by_symbol or {}
    name = name_by_symbol.get(hit.symbol) or str((hit.evidence or {}).get("name") or hit.symbol)
    sector = industries.get(hit.symbol) or "unknown"
    return StockSeed(
        symbol=hit.symbol,
        name=name,
        sector_code=sector,
        ret_20d=0.0,
        preliminary_score=0.55,
    )


def _focus_payload(hit: TriggerHit) -> dict[str, Any]:
    ev = hit.evidence or {}
    return {
        "trigger_code": hit.code,
        "severity": hit.severity,
        "symbol": hit.symbol,
        "title": str(ev.get("title") or hit.title or ""),
        "summary": str(ev.get("summary") or "")[:400],
        "direction": ev.get("l2_dir") or "",
        "urgency": ev.get("l2_urg") or "",
        "message": hit.message,
    }


def suggestion_from_view(view: StockView, *, direction: str = "") -> str:
    """Lightweight stance — full PortfolioEngine reweight is out of L3 scope."""
    dir_l = (direction or "").lower()
    if view.red_flags or (view.score < 0.4 and dir_l in {"neg", "negative", ""}):
        return "建议: 暂不新增；评估是否减仓，等待同业/后续公告确认。"
    if view.score >= 0.65 and dir_l in {"pos", "positive"}:
        return "建议: 事件偏正面，维持持仓观察，暂不加仓追高。"
    if dir_l in {"neg", "negative"}:
        return "建议: 偏负面但未构成清仓信号；暂不新增，设好止损观察。"
    return "建议: 暂不新增，等待更多确认后再评估仓位。"


def format_l3_message(hit: TriggerHit, view: StockView) -> str:
    ev = hit.evidence or {}
    direction = str(ev.get("l2_dir") or "")
    lines = [hit.message.strip(), "", f"分析: {view.thesis[:500]}"]
    if view.bear_points:
        lines.append(f"需注意: {view.bear_points[0].point[:200]}")
    if view.red_flags:
        lines.append(f"Red flag: {view.red_flags[0].flag[:160]}")
    lines.append(suggestion_from_view(view, direction=direction))
    return "\n".join(lines)


def _view_evidence_refs(view: StockView) -> list[str]:
    refs: list[str] = []
    for e in view.evidence[:6]:
        refs.append(e.ref_id or e.evidence_id)
    return refs


async def analyze_hit_l3(
    hit: TriggerHit,
    *,
    name_by_symbol: dict[str, str],
    industry_by_symbol: dict[str, str] | None = None,
    as_of: date,
    market: str = "CN",
    llm: LLMClient | None = None,
    budget: TokenBudget | None = None,
    tools: ToolRegistry | None = None,
    run_id: str | None = None,
) -> tuple[TriggerHit, float, L3Mode]:
    """Run StockAgent once for a single hit. Returns (enriched, cost_usd, mode)."""
    client = llm if llm is not None else build_llm_client(tier="medium")
    costs = CostTracker()
    mode: L3Mode = "heuristic"
    bundle: ResearchLlmBundle | None = None
    if llm_enabled(client) and budget is not None:
        bundle = ResearchLlmBundle(
            llm=client,
            budget=budget,
            costs=costs,
            allocation="monitoring",
        )
        mode = "llm"
    elif llm_enabled(client) and budget is None:
        # No TokenBudget → still try heuristic-only StockAgent (no HTTP path)
        mode = "heuristic"
        bundle = None

    seed = _seed_from_hit(hit, name_by_symbol=name_by_symbol, industry_by_symbol=industry_by_symbol)
    agent = StockAgent(seed, tools=tools, llm=bundle)
    ctx = AgentContext(
        as_of=as_of,
        market=market,
        run_id=run_id or f"monitor-l3-{hit.code}",
        upstream={"monitor_focus": _focus_payload(hit)},
    )
    view = await agent.run(ctx)
    cost = float(costs.total_usd_for("monitoring")) if bundle is not None else 0.0
    if bundle is not None and not costs.records:
        # LLM disabled mid-flight or skipped → treat as heuristic
        mode = "heuristic"

    evidence = dict(hit.evidence or {})
    evidence.update(
        {
            "l3_mode": mode,
            "l3_score": view.score,
            "l3_confidence": view.confidence,
            "l3_thesis": view.thesis[:400],
            "l3_suggestion": suggestion_from_view(
                view, direction=str(evidence.get("l2_dir") or "")
            ),
            "evidence_refs": _view_evidence_refs(view),
            "needs_deep_analysis": False,  # consumed
        }
    )
    enriched = hit.model_copy(
        update={
            "analysis_level": "L3",
            "message": format_l3_message(hit, view),
            "cost_usd": float(hit.cost_usd or 0.0) + cost,
            "evidence": evidence,
        }
    )
    return enriched, cost, mode


async def refine_hits_with_l3(
    hits: Sequence[TriggerHit],
    *,
    name_by_symbol: dict[str, str],
    industry_by_symbol: dict[str, str] | None = None,
    as_of: date,
    market: str = "CN",
    llm: LLMClient | None = None,
    budget: TokenBudget | None = None,
    monitor_budget: MonitorBudget | None = None,
    tools: ToolRegistry | None = None,
    enabled: bool = True,
) -> tuple[list[TriggerHit], L3Stats]:
    """Upgrade deep-flagged hits via StockAgent; respect L3 daily call cap."""
    stats = L3Stats(candidates=sum(1 for h in hits if needs_l3(h)))
    if not hits:
        return [], stats
    if not enabled:
        stats.mode = "disabled"
        stats.note = "disabled"
        return list(hits), stats

    out: list[TriggerHit] = []
    modes: list[L3Mode] = []

    for hit in hits:
        if not needs_l3(hit):
            out.append(hit)
            continue

        if monitor_budget is not None and not monitor_budget.allow_l3():
            stats.skipped_cap += 1
            reason = monitor_budget.degradation_reason() or "l3_cap"
            stats.note = reason
            logger.info("L3 skipped (budget): %s hit=%s", reason, hit.code)
            out.append(hit)
            continue

        # Reserve call slot before LLM work (counts even if later heuristic)
        if monitor_budget is not None and not monitor_budget.reserve_l3():
            stats.skipped_cap += 1
            stats.note = monitor_budget.degradation_reason() or "l3_cap"
            out.append(hit)
            continue

        try:
            enriched, cost, mode = await analyze_hit_l3(
                hit,
                name_by_symbol=name_by_symbol,
                industry_by_symbol=industry_by_symbol,
                as_of=as_of,
                market=market,
                llm=llm,
                budget=budget,
                tools=tools,
            )
            if monitor_budget is not None and cost > 0:
                monitor_budget.record_spend(cost, layer="l3", calls=0)
            stats.analyzed += 1
            stats.cost_usd += cost
            stats.symbols.append(enriched.symbol)
            modes.append(mode)
            out.append(enriched)
        except Exception as exc:  # noqa: BLE001
            logger.warning("L3 failed for %s: %s", hit.code, exc)
            stats.skipped_error += 1
            if not stats.note:
                stats.note = f"l3_error:{type(exc).__name__}"
            out.append(hit)

    if stats.analyzed == 0 and stats.skipped_cap:
        stats.mode = "skipped"
    elif modes and all(m == "heuristic" for m in modes):
        stats.mode = "heuristic"
    elif modes and any(m == "llm" for m in modes):
        stats.mode = "llm"
    elif stats.analyzed:
        stats.mode = modes[0] if modes else "heuristic"
    else:
        stats.mode = "skipped" if stats.candidates else "disabled"

    return out, stats


__all__ = [
    "L3Mode",
    "L3Stats",
    "analyze_hit_l3",
    "format_l3_message",
    "needs_l3",
    "refine_hits_with_l3",
    "suggestion_from_view",
]
