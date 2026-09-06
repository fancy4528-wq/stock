"""Unit tests for CalendarNormalizer dense expansion."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from quantagent.core.calendar import TradingCalendar
from quantagent.data.archive.parquet import ParquetArchive
from quantagent.data.normalizers.calendar import (
    CANONICAL_CALENDAR_COLUMNS,
    CalendarNormalizer,
    expand_dense_calendar,
)


def test_expand_dense_calendar_neighbors() -> None:
    opens = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 4)]  # skip Sep 3
    df = expand_dense_calendar(
        opens,
        market="CN",
        source="test",
        start=date(2026, 9, 1),
        end=date(2026, 9, 4),
    )
    assert df.columns == CANONICAL_CALENDAR_COLUMNS
    assert df.height == 4
    by = {r["trade_date"]: r for r in df.to_dicts()}
    assert by[date(2026, 9, 1)]["is_open"] is True
    assert by[date(2026, 9, 3)]["is_open"] is False
    assert by[date(2026, 9, 3)]["prev_trade_date"] == date(2026, 9, 2)
    assert by[date(2026, 9, 3)]["next_trade_date"] == date(2026, 9, 4)
    assert by[date(2026, 9, 2)]["next_trade_date"] == date(2026, 9, 4)


def test_normalize_akshare_open_list(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        {"trade_date": ["2026-09-01", "2026-09-02", "2026-09-04"]}
    )
    archive = ParquetArchive(tmp_path)
    batch = archive.write(
        raw,
        source="akshare",
        dataset="trading_calendar",
        target_date=date(2026, 9, 4),
        meta={"market": "CN", "start": "2026-09-01", "end": "2026-09-04"},
        collected_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
    )
    out = CalendarNormalizer().normalize(batch)
    assert out.filter(pl.col("is_open")).height == 3
    assert out.filter(~pl.col("is_open")).height == 1


def test_normalize_baostock_dense(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        {
            "calendar_date": ["2026-09-01", "2026-09-02", "2026-09-03"],
            "is_trading_day": ["1", "1", "0"],
        }
    )
    archive = ParquetArchive(tmp_path)
    batch = archive.write(
        raw,
        source="baostock",
        dataset="trading_calendar",
        target_date=date(2026, 9, 3),
        meta={"start": "2026-09-01", "end": "2026-09-03"},
        collected_at=datetime(2026, 9, 3, 8, 0, tzinfo=UTC),
    )
    out = CalendarNormalizer().normalize(batch)
    assert out.filter(pl.col("is_open")).height == 2
    assert out.filter(pl.col("trade_date") == date(2026, 9, 3))["is_open"][0] is False


def test_trading_calendar_navigation() -> None:
    opens = [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
    ]
    cal = TradingCalendar("CN", open_dates=opens)
    assert cal.is_trading_day(date(2026, 9, 2))
    assert not cal.is_trading_day(date(2026, 9, 5))
    assert cal.prev_trading_day(date(2026, 9, 4)) == date(2026, 9, 3)
    assert cal.next_trading_day(date(2026, 9, 2)) == date(2026, 9, 3)
    assert cal.on_or_before(date(2026, 9, 5)) == date(2026, 9, 4)
    assert cal.default_as_of(date(2026, 9, 4)) == date(2026, 9, 4)
    assert cal.default_as_of(date(2026, 9, 6)) == date(2026, 9, 4)
    assert cal.trading_days(date(2026, 9, 2), date(2026, 9, 4)) == [
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
    ]
