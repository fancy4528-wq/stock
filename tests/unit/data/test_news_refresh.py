"""Unit tests for daily news refresh soft-fail behavior."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantagent.data.ops.news_refresh import refresh_daily_news_events
from quantagent.shared.errors import SourceUnavailableError


@pytest.mark.asyncio
async def test_refresh_daily_news_soft_fails_collect() -> None:
    with (
        patch(
            "quantagent.data.ops.news_refresh.ClsNewsCollector"
        ) as cls_cls,
        patch(
            "quantagent.data.ops.news_refresh.EmNewsCollector"
        ) as em_cls,
        patch(
            "quantagent.data.ops.news_refresh.EmAnnouncementCollector"
        ) as ann_cls,
        patch(
            "quantagent.data.ops.news_refresh._extract_and_load",
            return_value=(2, 1),
        ),
    ):
        cls_inst = MagicMock()
        cls_inst.collect = AsyncMock(side_effect=SourceUnavailableError("cls down"))
        cls_cls.return_value = cls_inst

        em_batch = MagicMock()
        em_batch.source = "em"
        em_batch.row_count = 3
        em_batch.raw_path = "x.parquet"
        em_batch.target_date = date(2026, 9, 12)
        em_inst = MagicMock()
        em_inst.collect = AsyncMock(return_value=em_batch)
        em_cls.return_value = em_inst

        ann_inst = MagicMock()
        ann_inst.collect = AsyncMock(side_effect=SourceUnavailableError("empty day"))
        ann_cls.return_value = ann_inst

        with (
            patch(
                "quantagent.data.ops.news_refresh.NewsNormalizer"
            ) as norm_cls,
            patch(
                "quantagent.data.ops.news_refresh.NewsLoader"
            ) as loader_cls,
        ):
            import polars as pl

            norm_cls.return_value.normalize.return_value = pl.DataFrame(
                {
                    "source": ["em"],
                    "source_id": ["1"],
                    "title": ["t"],
                    "body": ["b"],
                    "published_at": [date(2026, 9, 12)],
                    "lang": ["zh"],
                    "content_hash": ["h"],
                    "raw_ref": [None],
                    "url": [None],
                    "related_symbol": [None],
                    "announce_type": [None],
                }
            )
            loader_cls.return_value.load.return_value = {
                "batch_id": 1,
                "rows_loaded": 3,
                "status": "success",
            }
            result = await refresh_daily_news_events(as_of=date(2026, 9, 12))

    assert result.news_rows == 3
    assert result.announcement_rows == 0
    assert result.events == 2
    assert any("cls" in d for d in result.degraded)
    assert any("em_announce" in d for d in result.degraded)
