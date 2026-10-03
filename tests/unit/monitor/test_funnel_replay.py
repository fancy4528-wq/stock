"""Unit tests: Gate 2b historical funnel replay (injected news, no DB)."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from quantagent.monitor.funnel.replay import (
    FunnelReplaySummary,
    format_cost_log_section,
    replay_funnel,
)
from quantagent.monitor.triggers.news import NewsFeedItem
from quantagent.positions.manual import save_position_book
from quantagent.positions.types import ManualPositionBook, PositionLot


def _book(path: Path) -> None:
    save_position_book(
        ManualPositionBook(
            account="funnel_replay_test",
            as_of=date(2026, 9, 18),
            cash=10_000,
            positions=[
                PositionLot(
                    symbol="600519.SH",
                    name="贵州茅台",
                    industry="食品饮料",
                    quantity=100,
                    avg_cost=1000,
                    entry_date=date(2026, 7, 1),
                    entry_high=1100,
                )
            ],
        ),
        path,
    )


def test_replay_l1_pass_rate_under_five_percent(tmp_path: Path) -> None:
    pos = tmp_path / "pos.yaml"
    _book(pos)
    d1 = date(2026, 9, 14)
    noise = [
        NewsFeedItem(
            title=f"无关快讯{i} 某科技公司发布新产品",
            summary="噪音",
            news_id=1000 + i,
            content_hash=f"noise-{i}",
            source="cls",
        )
        for i in range(40)
    ]
    hit = NewsFeedItem(
        title="贵州茅台签署重大合同 金额超预期",
        summary="与下游签订重大合同",
        news_id=1,
        content_hash="maotai-contract",
        source="cls",
    )
    summary = asyncio.run(
        replay_funnel(
            positions_path=pos,
            start=d1,
            end=d1,
            news_by_day={d1: [*noise, hit]},
            run_announcements=False,
            sessions=[d1],
            work_dir=tmp_path / "work",
        )
    )
    assert summary.scanned == 41
    assert summary.l1_passed == 1
    assert summary.l1_pass_rate is not None
    assert summary.l1_pass_rate < 0.05
    assert summary.l2_relevant == 1
    assert summary.l2_deep == 0
    assert summary.l2_to_l3_rate == 0.0
    assert summary.usd_per_day == 0.0
    assert summary.mode == "heuristic"
    gates = dict((name, verdict) for name, _a, _t, verdict in summary.gate_rows())
    assert gates["L1 pass rate"] == "PASS"
    assert gates["L2 → L3 rate"] == "PASS"
    assert gates["Monitor USD / day"] == "PASS"


def test_heuristic_l2_does_not_populate_cache(tmp_path: Path) -> None:
    pos = tmp_path / "pos.yaml"
    _book(pos)
    d1 = date(2026, 9, 14)
    d2 = date(2026, 9, 15)
    item = NewsFeedItem(
        title="贵州茅台签署重大合同",
        summary="重大合同",
        news_id=7,
        content_hash="same-hash",
        source="em",
    )
    extra = NewsFeedItem(
        title="贵州茅台签署重大合同 第二次转载",
        summary="重大合同",
        news_id=8,
        content_hash="same-hash",
        source="cls",
    )
    summary = asyncio.run(
        replay_funnel(
            positions_path=pos,
            start=d1,
            end=d2,
            news_by_day={d1: [item], d2: [item, extra]},
            run_announcements=False,
            sessions=[d1, d2],
            work_dir=tmp_path / "work",
        )
    )
    assert summary.l1_passed == 3
    assert summary.cache_hits == 0
    gates = dict((name, verdict) for name, _a, _t, verdict in summary.gate_rows())
    assert gates["L2 cache hit rate"] == "n/a"


def test_format_cost_log_section_contains_gates() -> None:
    summary = FunnelReplaySummary(
        start=date(2026, 9, 2),
        end=date(2026, 9, 30),
        positions_path="x.yaml",
        holdings=["600519.SH"],
        mode="heuristic",
    )
    text = format_cost_log_section(summary, generated_on=date(2026, 10, 3))
    assert "Gate 2b funnel replay" in text
    assert "L1 pass rate" in text
