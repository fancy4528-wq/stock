"""Synthetic + live ReportBundle pipelines for daily reports."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from quantagent.agents.base import AgentContext
from quantagent.agents.llm.factory import build_llm_client, build_token_budget
from quantagent.agents.llm.metering import CostTracker
from quantagent.agents.reporter import ReporterAgent
from quantagent.agents.reporter.validation_log import ValidationTracker
from quantagent.agents.tools.market import (
    FactorRankRow,
    FactorRow,
    MarketOverview,
    QualityCheck,
    ReportBundle,
    RiskNote,
    SectorRow,
    ShadowStatusRow,
)
from quantagent.core.repository.pit import PITRepository
from quantagent.evaluation.shadow import ShadowConfig, ShadowEngine, scores_from_brief
from quantagent.evaluation.shadow.stats import summarize_unfilled
from quantagent.evaluation.shadow.types import ShadowDayRecord
from quantagent.execution.broker.simulated import PriceBar
from quantagent.reporting.daily import write_daily_report
from quantagent.reporting.live import finalize_live_bundle, load_live_report_data

logger = logging.getLogger(__name__)


def make_run_id(as_of: date, market: str = "CN") -> str:
    return f"{as_of.strftime('%Y%m%d')}-{market.lower()}-daily"


def synthetic_universe(n: int = 50) -> list[str]:
    return [f"{600000 + i}.SH" for i in range(n)]


def build_synthetic_bars(symbols: list[str], as_of: date, *, seed: int = 7) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for i, sym in enumerate(symbols):
        # Deterministic pseudo-prices
        px = 10.0 + ((i * 17 + seed * 3) % 90)
        ret = ((i * 13 + seed) % 21 - 10) / 1000.0
        open_px = px
        close = px * (1.0 + ret)
        high = max(open_px, close) * 1.01
        low = min(open_px, close) * 0.99
        vol = 1_000_000.0 + i * 10_000
        bars.append(
            PriceBar(
                symbol=sym,
                trade_date=as_of,
                open=open_px,
                high=high,
                low=low,
                close=close,
                volume=vol,
                amount=vol * close,
                is_limit_up=(i == 3),  # one limit-up name for unfilled demo
            )
        )
    return bars


def build_synthetic_bundle(
    as_of: date,
    *,
    run_id: str | None = None,
    market: str = "CN",
    shadow_rows: list[ShadowStatusRow] | None = None,
    risk_notes: list[RiskNote] | None = None,
) -> ReportBundle:
    run_id = run_id or make_run_id(as_of, market)
    symbols = synthetic_universe(50)
    industries = ["电子", "食品饮料", "银行", "医药生物", "电力设备"]
    sectors = [
        SectorRow(
            industry=ind,
            n_names=10,
            ret_1d=0.01 - i * 0.004,
            ret_5d=0.02 - i * 0.008,
            ret_20d=0.05 - i * 0.02,
        )
        for i, ind in enumerate(industries)
    ]
    factors = [
        FactorRow(factor="mom_20d", long_short_1d=0.0031, ic_mean_20d=0.042),
        FactorRow(factor="mom_60d", long_short_1d=0.0024, ic_mean_20d=0.038),
        FactorRow(factor="rev_5d", long_short_1d=-0.0018, ic_mean_20d=-0.028),
        FactorRow(factor="vol_20d", long_short_1d=-0.0011, ic_mean_20d=-0.019),
        FactorRow(factor="turnover_20d", long_short_1d=0.0022, ic_mean_20d=0.035),
        FactorRow(factor="turnover_ratio_5_60", long_short_1d=0.0015, ic_mean_20d=0.021),
        FactorRow(factor="ep_ttm", long_short_1d=0.0009, ic_mean_20d=0.015),
        FactorRow(factor="amihud_illiq_20d", long_short_1d=-0.0007, ic_mean_20d=-0.012),
    ]
    ranks = [
        FactorRankRow(
            rank=i + 1,
            symbol=symbols[i],
            name=f"Demo{i}",
            score_pctile=0.98 - i * 0.02,
            ret_20d=0.18 - i * 0.03,
        )
        for i in range(5)
    ]
    return ReportBundle(
        as_of=as_of,
        run_id=run_id,
        market=market,
        market_overview=MarketOverview(
            as_of=as_of,
            index_close=3842.15,
            index_return_1d=0.0062,
            n_up=32,
            n_down=18,
            total_amount=4.86e10,
            amount_vs_20d=0.12,
            avg_turnover=0.0182,
            up_down_pctile_20d=0.68,
            amount_pctile_20d=0.74,
            turnover_pctile_20d=0.61,
        ),
        sectors=sectors,
        factors=factors,
        factor_ranks=ranks,
        factor_rank_name="mom_20d",
        shadow=shadow_rows or [],
        risk_notes=risk_notes
        or [
            RiskNote(text="当前回撤在阈值内（阈值 -15%）"),
        ],
        quality=[
            QualityCheck(name="行情完整性", ok=True, detail="50/50"),
            QualityCheck(name="双源校验", ok=True, detail="最大差异 0.02%"),
            QualityCheck(name="财务数据", ok=True, detail="无新增"),
            QualityCheck(name="PIT 校验", ok=True),
            QualityCheck(name="未来函数哨兵", ok=True),
        ],
        data_sources=[
            "行情：synthetic demo（无外部源）",
            "因子：synthetic 8 MVP factors (mom/rev/vol/turnover/ep/illiq)",
        ],
        code_version="dev",
    )


def _reject_stats(shadow_recs: list[ShadowDayRecord]) -> dict[str, int]:
    return summarize_unfilled(shadow_recs)


def _shadow_notes(shadow_recs: list[ShadowDayRecord]) -> list[RiskNote]:
    seen_unfilled: set[str] = set()
    unfilled_notes: list[RiskNote] = []
    for r in shadow_recs:
        for u in r.unfilled:
            key = f"{u['symbol']}:{u['reason']}"
            if key in seen_unfilled:
                continue
            seen_unfilled.add(key)
            unfilled_notes.append(RiskNote(text=f"未执行项：{u['symbol']} {u['reason']}"))
    return unfilled_notes


def _shadow_rows_from_recs(shadow_recs: list[ShadowDayRecord]) -> list[ShadowStatusRow]:
    return [
        ShadowStatusRow(
            portfolio=r.portfolio,
            ret_1d=r.ret_1d,
            ret_cum=r.ret_cum,
            max_drawdown=r.max_drawdown,
            n_positions=r.n_positions,
        )
        for r in shadow_recs
    ]


def _synthetic_agent_scores(symbols: list[str]) -> dict[str, float]:
    """Deterministic Agent-like ranking distinct from mom_20d factor order."""
    # Reverse-ish: mid-cap first so Top-N ≠ factor Top-N.
    n = len(symbols)
    return {sym: float((i * 7 + 3) % max(n, 1)) / max(n, 1) for i, sym in enumerate(symbols)}


async def _live_agent_scores(
    *,
    as_of: date,
    market: str,
    universe_code: str,
    repo: PITRepository,
    run_research: bool,
) -> tuple[dict[str, float], list[str]]:
    """Soft-run research DAG (heuristic, no RAG) for shadow_agent scores."""
    if not run_research:
        return {}, ["shadow_agent: research skipped"]
    try:
        from quantagent.agents.orchestrator import run_research_live

        result, _facts = await run_research_live(
            as_of=as_of,
            market=market,
            universe=universe_code,
            max_stocks=15,
            max_industries=5,
            include_knowledge=False,
            use_llm=False,
            repo=repo,
        )
        scores = scores_from_brief(result.brief)
        notes: list[str] = []
        if result.aborted:
            notes.append(f"shadow_agent: research aborted ({result.abort_reason})")
        if not scores:
            notes.append("shadow_agent: empty stock_ranking")
        return scores, notes
    except Exception as exc:  # noqa: BLE001 — soft-fail into degraded notes
        logger.warning("shadow_agent research failed: %s", exc)
        return {}, [f"shadow_agent: research failed ({type(exc).__name__}: {exc})"]


async def run_daily_pipeline(
    *,
    as_of: date | None = None,
    market: str = "CN",
    out_dir: Path | str = Path("docs/daily-reports"),
    shadow_dir: Path | str = Path("data/shadow"),
    synthetic: bool = True,
    write_cost_log: bool = True,
    universe_code: str = "mvp_cn_50",
    repo: PITRepository | None = None,
    run_id: str | None = None,
    degraded: list[str] | None = None,
    run_research: bool = True,
) -> Path:
    """Shadow step -> ReporterAgent -> markdown (synthetic or live PIT).

    LLM: ``build_llm_client()`` uses NullLLMClient unless ``LLM_API_KEY`` is set.
    Budget: ADR-0010 ``daily_research`` pool via ``TokenBudget`` (pre-call reserve).

    Live path soft-runs the research DAG (heuristic, ``use_llm=False``) to feed
    ``shadow_agent`` Top-N; failures become degraded notes, not hard stops.
    """
    costs = CostTracker()
    validations = ValidationTracker()
    budget = build_token_budget(day=as_of)
    agent = ReporterAgent(
        llm=build_llm_client(),
        cost_tracker=costs,
        validation_tracker=validations,
        budget=budget,
        allocation="daily_research",
    )

    if synthetic:
        as_of = as_of or (date.today() - timedelta(days=1))
        run_id = make_run_id(as_of, market)
        symbols = synthetic_universe(50)
        bars = build_synthetic_bars(symbols, as_of)
        scores = {sym: 1.0 - i * 0.01 for i, sym in enumerate(symbols)}
        agent_scores = _synthetic_agent_scores(symbols)
        engine = ShadowEngine(
            shadow_dir,
            cfg=ShadowConfig(baseline_n=50, factor_top_n=15, agent_top_n=15),
            code_version="dev",
        )
        engine.load_history_metrics()
        shadow_recs = await engine.step(
            as_of=as_of,
            run_id=run_id,
            bars=bars,
            baseline_symbols=symbols,
            factor_scores=scores,
            agent_scores=agent_scores,
        )
        reject_stats = _reject_stats(shadow_recs)
        bundle = build_synthetic_bundle(
            as_of,
            run_id=run_id,
            market=market,
            shadow_rows=_shadow_rows_from_recs(shadow_recs),
            risk_notes=_shadow_notes(shadow_recs)
            or [RiskNote(text="当前回撤在阈值内（阈值 -15%）")],
        ).model_copy(update={"reject_stats": reject_stats})
        ctx = AgentContext(as_of=as_of, market=market, run_id=run_id, code_version="dev")
    else:
        pit = repo or PITRepository()
        provisional = as_of or (date.today() - timedelta(days=1))
        provisional_run_id = run_id or make_run_id(provisional, market)
        live = load_live_report_data(
            pit,
            as_of=provisional,
            run_id=provisional_run_id,
            market=market,
            universe_code=universe_code,
            degraded=degraded,
        )
        as_of = live.as_of
        run_id = run_id or make_run_id(as_of, market)
        live = replace(
            live,
            run_id=run_id,
            bundle_partial=live.bundle_partial.model_copy(
                update={"as_of": as_of, "run_id": run_id}
            ),
        )
        agent_scores, agent_notes = await _live_agent_scores(
            as_of=as_of,
            market=market,
            universe_code=universe_code,
            repo=pit,
            run_research=run_research,
        )
        n = len(live.symbols)
        n_scored = len(live.factor_scores)
        n_agent = len(agent_scores)
        engine = ShadowEngine(
            shadow_dir,
            cfg=ShadowConfig(
                baseline_n=max(n, 1),
                factor_top_n=min(15, max(n_scored, 1)),
                agent_top_n=min(15, max(n_agent, 1)) if n_agent else 15,
            ),
            code_version="dev",
        )
        engine.load_history_metrics()
        shadow_recs = await engine.step(
            as_of=as_of,
            run_id=run_id,
            bars=live.bars,
            baseline_symbols=live.symbols,
            factor_scores=live.factor_scores,
            agent_scores=agent_scores,
        )
        reject_stats = _reject_stats(shadow_recs)
        risk = _shadow_notes(shadow_recs) + [RiskNote(text=n) for n in agent_notes]
        bundle = finalize_live_bundle(
            live,
            shadow_rows=_shadow_rows_from_recs(shadow_recs),
            risk_notes=risk,
        ).model_copy(update={"reject_stats": reject_stats})
        ctx = AgentContext(as_of=as_of, market=market, run_id=run_id, code_version="dev")

    report = await agent.run(ctx, bundle)
    if agent.degradations:
        extra = [
            RiskNote(text=f"预算降级[{d.allocation}/{d.action}]: {d.impact}")
            for d in agent.degradations
        ]
        bundle = bundle.model_copy(update={"risk_notes": list(bundle.risk_notes) + extra})
    out = Path(out_dir) / f"{as_of.isoformat()}.md"
    write_daily_report(report, bundle, out)
    if write_cost_log:
        costs.append_cost_log(Path("docs/cost-log.md"))
        validations.append_validation_log(Path("docs/reporter-validation-log.md"))
    return out
