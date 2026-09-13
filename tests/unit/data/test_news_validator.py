"""Unit tests for news validators and loader guards."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.data.loaders.news import NewsLoader
from quantagent.data.validators.news import NEWS_RULES
from quantagent.data.validators.report import RuleResult, ValidationReport
from quantagent.shared.errors import DataError, DataQualityError

CN_TZ = ZoneInfo("Asia/Shanghai")


def _ok_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "source": ["cls"],
            "source_id": ["abc"],
            "title": ["标题"],
            "body": ["正文"],
            "published_at": [datetime(2026, 9, 13, 10, 0, tzinfo=CN_TZ)],
            "lang": ["zh"],
            "content_hash": ["hash1"],
            "raw_ref": [None],
            "url": [None],
        }
    )


def test_news_rules_pass() -> None:
    df = _ok_df()
    for rule in NEWS_RULES:
        result = rule(df)
        assert result.status == "pass", result


def test_news_rules_empty_title() -> None:
    df = _ok_df().with_columns(pl.lit("").alias("title"))
    result = NEWS_RULES[1](df)
    assert result.status == "fail"
    assert result.code == "NEWS_002"


def test_news_loader_empty_and_blocking() -> None:
    loader = NewsLoader(engine=MagicMock())
    with pytest.raises(DataError, match="empty"):
        loader.load(pl.DataFrame(), source="cls")

    with patch.object(loader, "_start_batch", return_value=1), patch.object(
        loader, "_finish_batch"
    ):
        with pytest.raises(DataQualityError, match="blocking"):
            loader.load(
                _ok_df(),
                source="cls",
                validate=False,
                report=ValidationReport(
                    dataset="news",
                    check_date=date(2026, 9, 13),
                    results=[
                        RuleResult(code="X", level="FATAL", status="fail", detail="bad")
                    ],
                ),
            )
