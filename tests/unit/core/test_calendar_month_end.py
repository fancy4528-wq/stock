"""Unit tests for TradingCalendar.month_end_sessions."""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.core.calendar import TradingCalendar
from quantagent.shared.errors import DataError


def test_month_end_sessions_basic() -> None:
    # 2020-01: Jan 31 Fri open; Feb 28 Fri open; Mar 31 Tue open
    opens = [
        date(2020, 1, 30),
        date(2020, 1, 31),
        date(2020, 2, 27),
        date(2020, 2, 28),
        date(2020, 3, 30),
        date(2020, 3, 31),
    ]
    cal = TradingCalendar("CN", open_dates=opens)
    sessions = cal.month_end_sessions(date(2020, 1, 1), date(2020, 3, 31))
    assert sessions == [date(2020, 1, 31), date(2020, 2, 28), date(2020, 3, 31)]


def test_month_end_sessions_weekend_month_end() -> None:
    # 2021-01-31 was Sunday → last open Fri 29
    opens = [date(2021, 1, 28), date(2021, 1, 29), date(2021, 2, 1)]
    cal = TradingCalendar("CN", open_dates=opens)
    sessions = cal.month_end_sessions(date(2021, 1, 1), date(2021, 1, 31))
    assert sessions == [date(2021, 1, 29)]


def test_month_end_sessions_empty_calendar() -> None:
    cal = TradingCalendar("CN", open_dates=[])
    with pytest.raises(DataError):
        cal.month_end_sessions(date(2020, 1, 1), date(2020, 2, 1))
