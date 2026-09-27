"""Unit tests: L3 deep analysis via StockAgent + MonitorBudget cap."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from quantagent.agents.llm.client import NullLLMClient
from quantagent.monitor.budget import MonitorBudget, MonitorBudgetConfig
from quantagent.monitor.engine import run_monitor_once
from quantagent.monitor.funnel.l3_analysis import (
    needs_l3,
    refine_hits_with_l3,
)
from quantagent.monitor.suppression import SuppressionPolicy
from quantagent.monitor.types import TriggerHit
from quantagent.notify.base import LogNotifier
from quantagent.positions.manual import save_position_book
from quantagent.positions.types import ManualPositionBook, PositionLot


def _deep_hit(*, code: str = "NEWS_HIGH/1", severity: str = "high") -> TriggerHit:
    return TriggerHit(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        symbol="600519.SH",
        title="NEWS_HIGH",
        message="茅台重大合同",
        analysis_level="L2",
        evidence={
            "title": "茅台签署重大合同",
            "summary": "金额超预期",
            "l2_deep": True,
            "needs_deep_analysis": True,
            "l2_dir": "pos",
            "mentioned_symbols": ["600519.SH"],
        },
    )


def test_needs_l3_from_deep_flag() -> None:
    assert needs_l3(_deep_hit())
    plain = TriggerHit(
        code="NEWS_HIGH/2",
        severity="high",
        symbol="600519.SH",
        title="x",
        message="y",
        analysis_level="L2",
        evidence={"l2_deep": False},
    )
    assert not needs_l3(plain)


def test_needs_l3_critical_ann() -> None:
    hit = TriggerHit(
        code="ANN_CRITICAL/1",
        severity="critical",
        symbol="600519.SH",
        title="立案调查",
        message="收到立案调查",
        analysis_level="L1",
        evidence={},
    )
    assert needs_l3(hit)
    px = TriggerHit(
        code="PX_STOP_LOSS",
        severity="critical",
        symbol="600519.SH",
        title="止损",
        message="止损",
        analysis_level="L1",
    )
    assert not needs_l3(px)


def test_refine_l3_heuristic_enriches() -> None:
    hit = _deep_hit()
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=1.0, l3_max_calls_per_day=10),
        day=date.today(),
    )
    out, stats = asyncio.run(
        refine_hits_with_l3(
            [hit],
            name_by_symbol={"600519.SH": "贵州茅台"},
            industry_by_symbol={"600519.SH": "食品饮料"},
            as_of=date(2026, 9, 27),
            llm=NullLLMClient(),
            monitor_budget=mb,
        )
    )
    assert stats.analyzed == 1
    assert stats.mode == "heuristic"
    assert out[0].analysis_level == "L3"
    assert "分析:" in out[0].message
    assert "建议:" in out[0].message
    assert mb.l3_calls == 1


def test_l3_cap_skips_remaining() -> None:
    hits = [_deep_hit(code=f"NEWS_HIGH/{i}") for i in range(3)]
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=1.0, l3_max_calls_per_day=1),
        day=date.today(),
    )
    out, stats = asyncio.run(
        refine_hits_with_l3(
            hits,
            name_by_symbol={"600519.SH": "茅台"},
            as_of=date(2026, 9, 27),
            llm=NullLLMClient(),
            monitor_budget=mb,
        )
    )
    assert stats.analyzed == 1
    assert stats.skipped_cap == 2
    assert sum(1 for h in out if h.analysis_level == "L3") == 1


def test_engine_demo_ann_gets_l3(tmp_path: Path) -> None:
    """Demo 立案调查 is ANN_CRITICAL → L3 heuristic upgrade."""
    book = ManualPositionBook(
        account="test_l3",
        as_of=date(2026, 9, 18),
        cash=10_000,
        positions=[
            PositionLot(
                symbol="600519.SH",
                name="茅台",
                industry="食品饮料",
                quantity=100,
                avg_cost=1000,
                entry_date=date(2026, 7, 1),
                entry_high=1100,
            )
        ],
    )
    path = tmp_path / "pos.yaml"
    save_position_book(book, path)
    result = asyncio.run(
        run_monitor_once(
            positions_path=path,
            demo=True,
            notify=True,
            notifier=LogNotifier(),
            suppression_path=tmp_path / "sup.json",
            cache_path=tmp_path / "cache.json",
            budget_path=tmp_path / "budget.json",
            policy=SuppressionPolicy(quiet_hours=[]),
            persist_peak_nav=False,
            run_price=False,
            run_risk=False,
            run_news=False,
            run_announcements=True,
            run_l3=True,
        )
    )
    ann = [h for h in result.hits_raw if h.code.startswith("ANN_")]
    assert ann
    assert any(h.analysis_level == "L3" for h in ann)
    assert result.ran_l3
    assert result.news_l3_analyzed >= 1
    assert any("L3 mode=" in n for n in result.notes)


def test_engine_l3_disabled_keeps_l1_ann(tmp_path: Path) -> None:
    book = ManualPositionBook(
        account="test_l3_off",
        as_of=date(2026, 9, 18),
        cash=10_000,
        positions=[
            PositionLot(
                symbol="600519.SH",
                name="茅台",
                quantity=100,
                avg_cost=1000,
                entry_date=date(2026, 7, 1),
                entry_high=1100,
            )
        ],
    )
    path = tmp_path / "pos.yaml"
    save_position_book(book, path)
    result = asyncio.run(
        run_monitor_once(
            positions_path=path,
            demo=True,
            notify=False,
            suppression_path=tmp_path / "sup.json",
            budget_path=tmp_path / "budget.json",
            policy=SuppressionPolicy(quiet_hours=[]),
            persist_peak_nav=False,
            run_price=False,
            run_risk=False,
            run_news=False,
            run_announcements=True,
            run_l3=False,
        )
    )
    ann = [h for h in result.hits_raw if h.code.startswith("ANN_")]
    assert ann and all(h.analysis_level == "L1" for h in ann)
    assert result.ran_l3 is False
