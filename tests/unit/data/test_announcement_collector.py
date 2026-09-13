"""Tests for East Money announcement fetch (empty-day safe)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from quantagent.data.collectors.news.announcement import (
    EmAnnouncementCollector,
    fetch_em_notice_report,
)
from quantagent.shared.errors import SourceUnavailableError


def _empty_api_response() -> dict[str, object]:
    return {"data": {"total_hits": 0, "list": []}}


def _one_hit_response() -> dict[str, object]:
    return {
        "data": {
            "total_hits": 1,
            "list": [
                {
                    "art_code": "AN123",
                    "title": "测试公告",
                    "notice_date": "2026-09-12",
                    "codes": [
                        {
                            "stock_code": "600519",
                            "short_name": "贵州茅台",
                            "ann_type": "A",
                        }
                    ],
                    "columns": [{"column_name": "重大合同"}],
                }
            ],
        }
    }


def test_fetch_em_notice_empty_day() -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _empty_api_response()
    with patch("quantagent.data.collectors.news.announcement.requests.get", return_value=mock_resp):
        df = fetch_em_notice_report(date(2026, 9, 13))
    assert df.is_empty()


def test_fetch_em_notice_one_row() -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _one_hit_response()
    with patch("quantagent.data.collectors.news.announcement.requests.get", return_value=mock_resp):
        df = fetch_em_notice_report(date(2026, 9, 12))
    assert df.height == 1
    assert df["代码"][0] == "600519"
    assert "AN123" in str(df["网址"][0])


@pytest.mark.asyncio
async def test_collector_falls_back_from_empty_day(tmp_path: object) -> None:
    from pathlib import Path

    root = Path(tmp_path)
    collector = EmAnnouncementCollector(archive_root=root, fallback_days=3, rate_limit=0.0)

    async def fake_fetch(notice_date: date) -> pl.DataFrame:
        if notice_date == date(2026, 9, 13):
            return pl.DataFrame()
        return pl.DataFrame(
            {
                "代码": ["600519"],
                "名称": ["贵州茅台"],
                "公告标题": ["t"],
                "公告类型": ["其他"],
                "公告日期": ["2026-09-12"],
                "网址": ["https://example.com/x"],
            }
        )

    with patch.object(collector, "_fetch", side_effect=fake_fetch):
        batch = await collector.collect(date(2026, 9, 13))
    assert batch.target_date == date(2026, 9, 12)
    assert batch.meta["fallback_used"] is True
    assert batch.row_count == 1


@pytest.mark.asyncio
async def test_collector_all_empty_raises(tmp_path: object) -> None:
    from pathlib import Path

    collector = EmAnnouncementCollector(
        archive_root=Path(tmp_path), fallback_days=1, rate_limit=0.0
    )

    async def empty(_day: date) -> pl.DataFrame:
        return pl.DataFrame()

    with patch.object(collector, "_fetch", side_effect=empty):
        with pytest.raises(SourceUnavailableError, match="empty"):
            await collector.collect(date(2026, 9, 13))
