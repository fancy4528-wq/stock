"""Integration: load trading_calendar and read back via TradingCalendar."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.calendar import TradingCalendar
from quantagent.data.loaders import CalendarLoader
from quantagent.data.normalizers.calendar import expand_dense_calendar

pytestmark = pytest.mark.integration


def test_calendar_loader_and_service(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    opens = [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
    ]
    df = expand_dense_calendar(
        opens,
        market="CN",
        source="test",
        start=date(2026, 9, 1),
        end=date(2026, 9, 6),
    )
    result = CalendarLoader(engine).load(df, source="test", target_date=date(2026, 9, 6))
    assert result["status"] == "success"
    assert int(result["rows_loaded"]) == df.height

    with engine.connect() as conn:
        n_open = conn.execute(
            text(
                "SELECT COUNT(*) FROM trading_calendar WHERE market='CN' AND is_open"
            )
        ).scalar_one()
    assert int(n_open) == 4

    cal = TradingCalendar("CN", engine=engine)
    assert cal.is_trading_day(date(2026, 9, 4))
    assert not cal.is_trading_day(date(2026, 9, 5))
    assert cal.default_as_of(date(2026, 9, 6)) == date(2026, 9, 4)
