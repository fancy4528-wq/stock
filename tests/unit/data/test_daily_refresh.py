"""Unit tests for daily refresh window helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from quantagent.core.calendar import TradingCalendar
from quantagent.data.ops.daily_refresh import _ingest_window_start


def test_ingest_window_start_lookback_one() -> None:
    assert _ingest_window_start(date(2026, 9, 4), lookback_sessions=1, market="CN") == date(
        2026, 9, 4
    )


def test_ingest_window_start_uses_prev_sessions() -> None:
    opens = [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
    ]
    fake = TradingCalendar("CN", open_dates=opens)
    with patch(
        "quantagent.data.ops.daily_refresh.TradingCalendar",
        return_value=fake,
    ):
        start = _ingest_window_start(date(2026, 9, 4), lookback_sessions=3, market="CN")
    assert start == date(2026, 9, 2)


def test_ingest_window_start_empty_calendar_fallback() -> None:
    empty = TradingCalendar("CN", open_dates=[])
    with patch(
        "quantagent.data.ops.daily_refresh.TradingCalendar",
        return_value=empty,
    ):
        start = _ingest_window_start(date(2026, 9, 4), lookback_sessions=3, market="CN")
    assert start <= date(2026, 9, 4)
