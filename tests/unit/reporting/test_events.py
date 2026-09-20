"""Tests for report event loader."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from quantagent.reporting.events import load_events_for_as_of

CN_TZ = ZoneInfo("Asia/Shanghai")


def test_load_events_for_as_of_maps_rows() -> None:
    repo = MagicMock()
    repo.fetch_events_on_day.return_value = [
        {
            "event_id": 9,
            "news_id": 3,
            "event_type": "contract",
            "summary": "中标金额1.2亿元",
            "direction": "positive",
            "impact": 0.8,
            "visible_at": datetime(2026, 9, 11, 16, 0, tzinfo=CN_TZ),
            "news_source": "em_announce",
            "symbols": ["600519.SH"],
        }
    ]

    rows = load_events_for_as_of(
        date(2026, 9, 11),
        repo=repo,
        universe_symbols=["600519.SH"],
        limit=5,
    )
    assert len(rows) == 1
    assert rows[0].event_id == 9
    assert rows[0].symbols == ["600519.SH"]
    assert rows[0].event_type == "contract"
    repo.fetch_events_on_day.assert_called_once()


def test_load_events_soft_fails() -> None:
    repo = MagicMock()
    repo.fetch_events_on_day.side_effect = RuntimeError("db down")
    assert load_events_for_as_of(date(2026, 9, 11), repo=repo) == []
