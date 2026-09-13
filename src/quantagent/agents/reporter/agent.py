"""ReporterAgent: structured factual daily report from ReportBundle tools."""

from __future__ import annotations

import json
from typing import Any

from quantagent.agents.base import AgentContext, Evidence
from quantagent.agents.llm.budget import DegradationNote, TokenBudget
from quantagent.agents.llm.call import complete_with_budget
from quantagent.agents.llm.client import LLMClient, NullLLMClient
from quantagent.agents.llm.metering import CostRecord, CostTracker
from quantagent.agents.reporter.prompts import load_common_constraints, load_prompt
from quantagent.agents.reporter.schema import DailyReport, Observation
from quantagent.agents.reporter.validation_log import ValidationRecord, ValidationTracker
from quantagent.agents.tools.market import (
    ReportBundle,
    get_factor_performance,
    get_market_overview,
    get_sector_performance,
    get_shadow_status,
)
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import (
    BudgetDegrade,
    BudgetExceeded,
    BudgetSkip,
    EvidenceMissingError,
    SchemaValidationError,
)


def _pct(x: float) -> str:
    return f"{x:+.2%}"


def _build_evidence(bundle: ReportBundle) -> list[Evidence]:
    m = bundle.market_overview
    evidence = [
        Evidence(
            evidence_id="ev-mkt",
            kind="price",
            ref_id=f"index:{m.index_symbol}:{bundle.as_of.isoformat()}",
            excerpt=(f"{m.index_symbol} close={m.index_close:.2f} ret_1d={m.index_return_1d:+.4f}"),
            as_of=bundle.as_of,
        ),
        Evidence(
            evidence_id="ev-breadth",
            kind="price",
            ref_id=f"breadth:{bundle.run_id}",
            excerpt=(
                f"up={m.n_up} down={m.n_down} amount={m.total_amount:.0f} "
                f"amount_yi={m.total_amount / 1e8:.1f} "
                f"amount_vs_20d={m.amount_vs_20d:+.4f} avg_turnover={m.avg_turnover:.4f}"
            ),
            as_of=bundle.as_of,
        ),
    ]
    for i, sector in enumerate(bundle.sectors):
        evidence.append(
            Evidence(
                evidence_id=f"ev-sector-{i}",
                kind="sector",
                ref_id=f"sector:{sector.industry}:{bundle.as_of.isoformat()}",
                excerpt=(
                    f"{sector.industry} ret_1d={sector.ret_1d:+.4f} "
                    f"ret_5d={sector.ret_5d:+.4f} ret_20d={sector.ret_20d:+.4f} n={sector.n_names}"
                ),
                as_of=bundle.as_of,
            )
        )
    if bundle.factors:
        for factor in bundle.factors:
            ic = "" if factor.ic_mean_20d is None else f" ic20={factor.ic_mean_20d:+.4f}"
            evidence.append(
                Evidence(
                    evidence_id=f"ev-factor-{factor.factor}",
                    kind="factor",
                    ref_id=f"factor:{factor.factor}:{bundle.as_of.isoformat()}",
                    excerpt=f"{factor.factor} LS={factor.long_short_1d:+.4f}{ic}",
                    as_of=bundle.as_of,
                )
            )
    else:
        evidence.append(
            Evidence(
                evidence_id="ev-factor-empty",
                kind="factor",
                ref_id=f"factor:none:{bundle.as_of.isoformat()}",
                excerpt="no factor rows in bundle",
                as_of=bundle.as_of,
            )
        )
    for i, shadow in enumerate(bundle.shadow):
        evidence.append(
            Evidence(
                evidence_id=f"ev-shadow-{i}",
                kind="shadow",
                ref_id=f"shadow:{shadow.portfolio}:{bundle.as_of.isoformat()}",
                excerpt=(
                    f"{shadow.portfolio} ret_1d={shadow.ret_1d:+.4f} "
                    f"cum={shadow.ret_cum:+.4f} mdd={shadow.max_drawdown:+.4f} "
                    f"n={shadow.n_positions}"
                ),
                as_of=bundle.as_of,
            )
        )
    for i, ev in enumerate(bundle.events[:8]):
        syms = ",".join(ev.symbols[:3]) if ev.symbols else "-"
        evidence.append(
            Evidence(
                evidence_id=f"ev-event-{i}",
                kind="news",
                ref_id=f"event:{ev.event_id}",
                excerpt=(
                    f"type={ev.event_type} dir={ev.direction} symbols={syms} {ev.summary[:120]}"
                ),
                as_of=bundle.as_of,
            )
        )
    return evidence


def build_deterministic_report(bundle: ReportBundle) -> DailyReport:
    """Fact-only summaries from tool outputs (no LLM, no causal language)."""
    m = get_market_overview(bundle)
    sectors = get_sector_performance(bundle)
    factors = get_factor_performance(bundle)
    shadow = get_shadow_status(bundle)

    market_summary = (
        f"数据显示 {m.index_symbol} 收于 {m.index_close:.2f}，"
        f"较前值 {_pct(m.index_return_1d)}。"
        f"池内 {m.n_up} 上涨 / {m.n_down} 下跌，"
        f"成交额合计 {m.total_amount / 1e8:.1f} 亿元，"
        f"较 20 日均值 {_pct(m.amount_vs_20d)}。"
    )[:400]

    if sectors:
        top = max(sectors, key=lambda s: s.ret_1d)
        bot = min(sectors, key=lambda s: s.ret_1d)
        sector_summary = (
            f"数据显示池内行业当日涨幅最高为 {top.industry}（{_pct(top.ret_1d)}，"
            f"n={top.n_names}），最低为 {bot.industry}（{_pct(bot.ret_1d)}）。"
        )[:400]
    else:
        sector_summary = "数据显示当日无可用行业分组统计。"

    if factors:
        bits = ", ".join(f"{f.factor} 多空 {_pct(f.long_short_1d)}" for f in factors[:4])
        factor_summary = f"数据显示因子当日多空收益：{bits}。"[:300]
    else:
        factor_summary = "数据显示当日无可用因子多空统计。"

    if bundle.events:
        types = sorted({e.event_type for e in bundle.events})
        event_summary = (
            f"数据显示当日结构化事件 {len(bundle.events)} 条（类型：{', '.join(types[:5])}）。"
        )[:400]
    else:
        event_summary = "数据显示当日无入库结构化事件（或尚未抽取）。"

    observations: list[Observation] = []
    if abs(m.amount_vs_20d) >= 0.10:
        observations.append(
            Observation(
                statement=f"池内成交额较 20 日均值偏离 {_pct(m.amount_vs_20d)}",
                metric="amount_vs_20d",
                value=float(m.amount_vs_20d),
                evidence_refs=["ev-breadth"],
            )
        )
    if sectors:
        top = max(sectors, key=lambda s: s.ret_1d)
        top_idx = next(i for i, s in enumerate(bundle.sectors) if s.industry == top.industry)
        observations.append(
            Observation(
                statement=f"{top.industry} 当日平均涨幅 {_pct(top.ret_1d)}",
                metric="sector_ret_1d",
                value=float(top.ret_1d),
                evidence_refs=[f"ev-sector-{top_idx}"],
            )
        )
    if factors:
        f0 = factors[0]
        observations.append(
            Observation(
                statement=f"{f0.factor} 多空 {_pct(f0.long_short_1d)}",
                metric="factor_ls_1d",
                value=float(f0.long_short_1d),
                evidence_refs=[f"ev-factor-{f0.factor}"],
            )
        )
    if shadow:
        s0 = shadow[0]
        observations.append(
            Observation(
                statement=f"{s0.portfolio} 当日收益 {_pct(s0.ret_1d)}",
                metric="shadow_ret_1d",
                value=float(s0.ret_1d),
                evidence_refs=["ev-shadow-0"],
            )
        )
    if bundle.events:
        e0 = bundle.events[0]
        observations.append(
            Observation(
                statement=f"事件 {e0.event_type}: {e0.summary[:80]}",
                metric="event_count",
                value=float(len(bundle.events)),
                evidence_refs=["ev-event-0"],
            )
        )

    quality_fail = [q for q in bundle.quality if not q.ok]
    data_quality_note = None
    if quality_fail:
        data_quality_note = "；".join(f"{q.name}: {q.detail or 'FAIL'}" for q in quality_fail)[:300]

    evidence = _build_evidence(bundle)
    report = DailyReport(
        as_of=bundle.as_of,
        run_id=bundle.run_id,
        market_summary=market_summary,
        sector_summary=sector_summary,
        factor_summary=factor_summary,
        event_summary=event_summary,
        notable_observations=observations[:5],
        data_quality_note=data_quality_note,
        evidence=evidence,
    )
    require_evidence(report.evidence, min_count=3)
    return validate_model(report)  # type: ignore[return-value]


def _parse_llm_daily_report(text: str, bundle: ReportBundle) -> DailyReport:
    raw: dict[str, Any] = json.loads(text)
    raw.setdefault("as_of", bundle.as_of.isoformat())
    raw.setdefault("run_id", bundle.run_id)
    if "evidence" not in raw:
        raw["evidence"] = [e.model_dump(mode="json") for e in _build_evidence(bundle)]
    try:
        report = DailyReport.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise SchemaValidationError(str(exc)) from exc
    require_evidence(report.evidence, min_count=3)
    return report


class ReporterAgent:
    """MVP single Agent: facts from tools -> DailyReport (deterministic or LLM)."""

    name = "reporter"
    tier = "medium"

    def __init__(
        self,
        llm: LLMClient | None = None,
        *,
        cost_tracker: CostTracker | None = None,
        validation_tracker: ValidationTracker | None = None,
        budget: TokenBudget | None = None,
        allocation: str = "daily_research",
    ) -> None:
        self._llm: LLMClient = llm or NullLLMClient()
        self._costs = cost_tracker or CostTracker()
        self._validations = validation_tracker or ValidationTracker()
        self._budget = budget
        self._allocation = allocation
        self.degradations: list[DegradationNote] = []

    def _record_validation(
        self,
        *,
        ctx: AgentContext,
        mode: str,
        ok: bool,
        error: BaseException | None = None,
    ) -> None:
        err_type = type(error).__name__ if error is not None else None
        detail = str(error)[:200] if error is not None else None
        self._validations.add(
            ValidationRecord(
                run_id=ctx.run_id,
                as_of=ctx.as_of,
                agent=self.name,
                mode=mode,
                ok=ok,
                error_type=err_type,
                detail=detail,
            )
        )

    def _add_cost(
        self,
        *,
        run_id: str,
        model: str,
        mode: str,
        cost_usd: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self._costs.add(
            CostRecord(
                run_id=run_id,
                agent=self.name,
                model=model,
                mode=mode,
                allocation=self._allocation,
                cost_usd=cost_usd,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

    async def _deterministic(
        self,
        ctx: AgentContext,
        bundle: ReportBundle,
        *,
        mode: str = "deterministic",
        model: str = "deterministic",
    ) -> DailyReport:
        try:
            report = build_deterministic_report(bundle)
        except (SchemaValidationError, EvidenceMissingError, ValueError) as exc:
            self._record_validation(ctx=ctx, mode="deterministic", ok=False, error=exc)
            raise
        self._record_validation(ctx=ctx, mode="deterministic", ok=True)
        self._add_cost(run_id=ctx.run_id, model=model, mode=mode, cost_usd=0.0)
        return report

    async def run(self, ctx: AgentContext, bundle: ReportBundle) -> DailyReport:
        if isinstance(self._llm, NullLLMClient) or self._llm.model == "null":
            return await self._deterministic(ctx, bundle)

        system = load_common_constraints() + "\n\n" + load_prompt("reporter")
        payload = {
            "as_of": bundle.as_of.isoformat(),
            "run_id": bundle.run_id,
            "market": get_market_overview(bundle).model_dump(mode="json"),
            "sectors": [s.model_dump(mode="json") for s in get_sector_performance(bundle)],
            "factors": [f.model_dump(mode="json") for f in get_factor_performance(bundle)],
            "shadow": [s.model_dump(mode="json") for s in get_shadow_status(bundle)],
        }
        user = "根据以下结构化数据生成 DailyReport JSON（仅事实，无买卖建议）：\n" + json.dumps(
            payload, ensure_ascii=False
        )
        tier = self.tier
        budget = self._budget or TokenBudget()

        try:
            resp, _res = await complete_with_budget(
                self._llm,
                budget,
                allocation=self._allocation,
                tier=tier,
                system=system,
                user=user,
            )
        except BudgetDegrade as exc:
            self.degradations.extend(budget.degradations[-1:])
            # Retry once on small tier; if still blocked, deterministic.
            try:
                resp, _res = await complete_with_budget(
                    self._llm,
                    budget,
                    allocation=self._allocation,
                    tier=exc.suggested_tier,
                    system=system,
                    user=user,
                )
            except (BudgetDegrade, BudgetSkip, BudgetExceeded):
                note = DegradationNote(
                    allocation=self._allocation,
                    action="degrade",
                    reason=str(exc),
                    impact="日报改为确定性摘要（未调用 LLM）",
                )
                self.degradations.append(note)
                return await self._deterministic(
                    ctx, bundle, mode="budget_degrade", model="deterministic"
                )
        except (BudgetSkip, BudgetExceeded) as exc:
            note = DegradationNote(
                allocation=self._allocation,
                action=getattr(exc, "action", "abort"),
                reason=str(exc),
                impact="日报改为确定性摘要（预算拦截，未产生 LLM 费用）",
            )
            self.degradations.append(note)
            return await self._deterministic(ctx, bundle, mode="budget_skip", model="deterministic")

        self._add_cost(
            run_id=ctx.run_id,
            model=resp.model,
            mode="llm",
            cost_usd=resp.cost_usd,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
        )
        if not resp.text.strip():
            return await self._deterministic(ctx, bundle)
        try:
            report = _parse_llm_daily_report(resp.text, bundle)
        except (
            SchemaValidationError,
            EvidenceMissingError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            self._record_validation(ctx=ctx, mode="llm", ok=False, error=exc)
            raise SchemaValidationError(str(exc)) from exc
        self._record_validation(ctx=ctx, mode="llm", ok=True)
        return report
