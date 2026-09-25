"""Unit tests: monitor session + resident loop."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantagent.monitor.engine import run_monitor_loop, run_monitor_once
from quantagent.monitor.session import MonitorSchedule, SessionWindow, in_cash_session
from quantagent.monitor.suppression import SuppressionPolicy
from quantagent.notify.base import LogNotifier
from quantagent.positions.manual import save_position_book
from quantagent.positions.types import ManualPositionBook, PositionLot


def test_in_cash_session_morning() -> None:
    sched = MonitorSchedule(
        timezone="Asia/Shanghai",
        windows=[
            SessionWindow(start="09:30", end="11:30"),
            SessionWindow(start="13:00", end="15:00"),
        ],
    )
    # Fixed weekday that is Mon–Fri; calendar may miss — weekday fallback ok
    morning = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert morning.weekday() < 5
    assert in_cash_session(morning, schedule=sched, market="CN") is True
    night = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert in_cash_session(night, schedule=sched, market="CN") is False


def test_run_monitor_once_includes_demo_announcement(tmp_path: Path) -> None:
    book = ManualPositionBook(
        account="test_ann",
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
            policy=SuppressionPolicy(quiet_hours=[]),
            persist_peak_nav=False,
            run_announcements=True,
        )
    )
    codes = {h.code.split("/")[0] for h in result.hits_raw}
    assert "ANN_CRITICAL" in codes
    assert result.ran_announcements


def test_run_monitor_loop_two_cycles(tmp_path: Path) -> None:
    book = ManualPositionBook(
        account="test_loop",
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
    seen: list[int] = []

    def on_cycle(n: int, _result: object) -> None:
        seen.append(n)

    loop = asyncio.run(
        run_monitor_loop(
            positions_path=path,
            demo=True,
            notify=True,
            notifier=LogNotifier(),
            suppression_path=tmp_path / "sup.json",
            max_cycles=2,
            interval_seconds=0.05,
            respect_sessions=False,
            on_cycle=on_cycle,
        )
    )
    assert loop.cycles == 2
    assert seen == [1, 2]
    assert loop.last is not None
    assert loop.stopped_reason == "completed"
