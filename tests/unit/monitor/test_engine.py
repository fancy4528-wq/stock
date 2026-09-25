"""Unit tests: monitor engine once-loop."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from quantagent.monitor.engine import run_monitor_once
from quantagent.monitor.suppression import SuppressionPolicy
from quantagent.notify.base import LogNotifier
from quantagent.positions.manual import save_position_book
from quantagent.positions.types import ManualPositionBook, PositionLot


def test_run_monitor_once_demo(tmp_path: Path) -> None:
    book = ManualPositionBook(
        account="test_engine",
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
    state_path = tmp_path / "sup.json"

    result = asyncio.run(
        run_monitor_once(
            positions_path=path,
            demo=True,
            notify=True,
            notifier=LogNotifier(),
            suppression_path=state_path,
            policy=SuppressionPolicy(quiet_hours=[]),
            persist_peak_nav=True,
        )
    )
    assert result.quotes
    assert result.hits_raw  # stop loss / limit down etc.
    assert result.hits_sent
    assert all(d.ok for d in result.deliveries)
    # Second run should cooldown-suppress same codes
    result2 = asyncio.run(
        run_monitor_once(
            positions_path=path,
            demo=True,
            notify=True,
            notifier=LogNotifier(),
            suppression_path=state_path,
            policy=SuppressionPolicy(quiet_hours=[]),
            persist_peak_nav=False,
        )
    )
    assert len(result2.suppressed) >= 1
