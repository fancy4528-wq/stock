"""Synthetic ReportBundle + end-to-end daily pipeline (no DB)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from quantagent.agents.base import AgentContext
from quantagent.agents.llm.client import NullLLMClient
from quantagent.agents.llm.metering import CostTracker
from quantagent.agents.reporter import ReporterAgent
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
from quantagent.evaluation.shadow import ShadowConfig, ShadowEngine
from quantagent.execution.broker.simulated import PriceBar
from quantagent.reporting.daily import write_daily_report


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
        FactorRow(factor="rev_5d", long_short_1d=-0.0018, ic_mean_20d=-0.028),
        FactorRow(factor="turnover_20d", long_short_1d=0.0022, ic_mean_20d=0.035),
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
            "因子：synthetic mom_20d / rev_5d / turnover_20d",
        ],
        code_version="dev",
    )


async def run_daily_pipeline(
    *,
    as_of: date | None = None,
    market: str = "CN",
    out_dir: Path | str = Path("docs/daily-reports"),
    shadow_dir: Path | str = Path("data/shadow"),
    synthetic: bool = True,
    write_cost_log: bool = False,
) -> Path:
    """Shadow step -> ReporterAgent -> markdown. Synthetic-only for MVP CLI."""
    as_of = as_of or (date.today() - timedelta(days=1))
    run_id = make_run_id(as_of, market)
    symbols = synthetic_universe(50)
    bars = build_synthetic_bars(symbols, as_of)
    scores = {sym: 1.0 - i * 0.01 for i, sym in enumerate(symbols)}

    engine = ShadowEngine(
        shadow_dir,
        cfg=ShadowConfig(baseline_n=50, factor_top_n=15),
        code_version="dev",
    )
    engine.load_history_metrics()
    shadow_recs = await engine.step(
        as_of=as_of,
        run_id=run_id,
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
    )
    shadow_rows = [
        ShadowStatusRow(
            portfolio=r.portfolio,
            ret_1d=r.ret_1d,
            ret_cum=r.ret_cum,
            max_drawdown=r.max_drawdown,
            n_positions=r.n_positions,
        )
        for r in shadow_recs
    ]
    seen_unfilled: set[str] = set()
    unfilled_notes: list[RiskNote] = []
    for r in shadow_recs:
        for u in r.unfilled:
            key = f"{u['symbol']}:{u['reason']}"
            if key in seen_unfilled:
                continue
            seen_unfilled.add(key)
            unfilled_notes.append(
                RiskNote(text=f"未执行项：{u['symbol']} {u['reason']}")
            )

    if not synthetic:
        raise NotImplementedError("live report pipeline requires DB ingest (post-MVP wiring)")

    bundle = build_synthetic_bundle(
        as_of,
        run_id=run_id,
        market=market,
        shadow_rows=shadow_rows,
        risk_notes=unfilled_notes or [RiskNote(text="当前回撤在阈值内（阈值 -15%）")],
    )
    costs = CostTracker()
    agent = ReporterAgent(llm=NullLLMClient(), cost_tracker=costs)
    ctx = AgentContext(as_of=as_of, market=market, run_id=run_id, code_version="dev")
    report = await agent.run(ctx, bundle)
    out = Path(out_dir) / f"{as_of.isoformat()}.md"
    write_daily_report(report, bundle, out)
    if write_cost_log:
        costs.append_cost_log(Path("docs/cost-log.md"))
    return out
