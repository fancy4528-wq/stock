"""ReporterAgent: structured factual daily report from ReportBundle tools."""

from __future__ import annotations

import json
from typing import Any

from quantagent.agents.base import AgentContext, Evidence
from quantagent.agents.llm.client import LLMClient, NullLLMClient
from quantagent.agents.llm.metering import CostRecord, CostTracker
from quantagent.agents.reporter.prompts import load_common_constraints, load_prompt
from quantagent.agents.reporter.schema import DailyReport, Observation
from quantagent.agents.tools.market import (
    ReportBundle,
    get_factor_performance,
    get_market_overview,
    get_sector_performance,
    get_shadow_status,
)
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import SchemaValidationError


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
            excerpt=f"up={m.n_up} down={m.n_down} amount={m.total_amount:.0f}",
            as_of=bundle.as_of,
        ),
    ]
    if bundle.factors:
        f0 = bundle.factors[0]
        evidence.append(
            Evidence(
                evidence_id="ev-factor",
                kind="factor",
                ref_id=f"factor:{f0.factor}:{bundle.as_of.isoformat()}",
                excerpt=f"{f0.factor} LS={f0.long_short_1d:+.4f}",
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
    if bundle.shadow:
        s0 = bundle.shadow[0]
        evidence.append(
            Evidence(
                evidence_id="ev-shadow",
                kind="shadow",
                ref_id=f"shadow:{s0.portfolio}:{bundle.as_of.isoformat()}",
                excerpt=f"{s0.portfolio} ret_1d={s0.ret_1d:+.4f} cum={s0.ret_cum:+.4f}",
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
        observations.append(
            Observation(
                statement=f"{top.industry} 当日平均涨幅 {_pct(top.ret_1d)}",
                metric="sector_ret_1d",
                value=float(top.ret_1d),
                evidence_refs=["ev-mkt"],
            )
        )
    if shadow:
        s0 = shadow[0]
        ev_ids = [e.evidence_id for e in _build_evidence(bundle)]
        shadow_ref = "ev-shadow" if "ev-shadow" in ev_ids else "ev-mkt"
        observations.append(
            Observation(
                statement=f"{s0.portfolio} 当日收益 {_pct(s0.ret_1d)}",
                metric="shadow_ret_1d",
                value=float(s0.ret_1d),
                evidence_refs=[shadow_ref],
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
    ) -> None:
        self._llm: LLMClient = llm or NullLLMClient()
        self._costs = cost_tracker or CostTracker()

    async def run(self, ctx: AgentContext, bundle: ReportBundle) -> DailyReport:
        if isinstance(self._llm, NullLLMClient) or self._llm.model == "null":
            report = build_deterministic_report(bundle)
            self._costs.add(
                CostRecord(
                    run_id=ctx.run_id,
                    agent=self.name,
                    model="deterministic",
                    mode="deterministic",
                    cost_usd=0.0,
                )
            )
            return report

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
        resp = await self._llm.complete(system=system, user=user)
        self._costs.add(
            CostRecord(
                run_id=ctx.run_id,
                agent=self.name,
                model=resp.model,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                cost_usd=resp.cost_usd,
                mode="llm",
            )
        )
        if not resp.text.strip():
            return build_deterministic_report(bundle)
        return _parse_llm_daily_report(resp.text, bundle)
