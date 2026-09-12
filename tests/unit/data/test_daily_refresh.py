"""Unit tests for daily refresh window helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from quantagent.core.calendar import TradingCalendar
from quantagent.data.contracts import RawBatch
from quantagent.data.ops.daily_refresh import (
    DailyRefreshResult,
    _collect_and_load_prices,
    _collect_price_batch,
    _ingest_window_start,
    _peer_source,
    _price_collector,
    refresh_daily_market_data,
)
from quantagent.data.ops.degrade import DegradedSource
from quantagent.shared.errors import DataError


def _batch(*, source: str = "baostock", dataset: str = "price_daily", rows: int = 1) -> RawBatch:
    return RawBatch(
        batch_id=1,
        source=source,
        dataset=dataset,
        target_date=date(2026, 9, 1),
        raw_path=Path("x.parquet"),
        row_count=rows,
        collected_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


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


def test_ingest_window_start_data_error_fallback() -> None:
    cal = MagicMock()
    cal.is_empty.return_value = False
    cal.prev_trading_day.side_effect = DataError("no prior")
    with patch("quantagent.data.ops.daily_refresh.TradingCalendar", return_value=cal):
        assert _ingest_window_start(date(2026, 9, 4), lookback_sessions=3, market="CN") == date(
            2026, 9, 4
        )


def test_peer_source_and_price_collector() -> None:
    assert _peer_source("akshare") == "baostock"
    assert _peer_source("baostock") == "akshare"
    assert _price_collector("akshare", None).__class__.__name__ == "AksharePriceCollector"
    assert _price_collector("baostock", None).__class__.__name__ == "BaostockPriceCollector"
    with pytest.raises(ValueError, match="unsupported"):
        _price_collector("tushare", None)


async def test_collect_price_batch_records_degrade() -> None:
    batch = _batch()
    degraded = DegradedSource(
        source="akshare",
        dataset="price_daily",
        reason="down",
        fallback="baostock",
    )
    with patch(
        "quantagent.data.ops.daily_refresh.try_collect_with_fallback",
        new=AsyncMock(return_value=(batch, degraded)),
    ):
        out, note = await _collect_price_batch(
            symbols=["600519.SH"],
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            source="akshare",
            archive_root=None,
        )
    assert out is batch
    assert note is not None
    assert "down" in note


async def test_collect_and_load_prices_index_and_empty() -> None:
    empty_batch = _batch(source="akshare", dataset="index_daily", rows=0)
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=empty_batch)
    with (
        patch(
            "quantagent.data.ops.daily_refresh.AkshareIndexCollector",
            return_value=collector,
        ),
        patch(
            "quantagent.data.ops.daily_refresh.PriceNormalizer"
        ) as norm,
    ):
        norm.return_value.normalize.return_value = pl.DataFrame()
        n = await _collect_and_load_prices(
            symbols=["000300.SH"],
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            source="akshare",
            kind="index",
            archive_root=None,
        )
    assert n == 0

    with pytest.raises(ValueError, match="akshare only"):
        await _collect_and_load_prices(
            symbols=["000300.SH"],
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            source="baostock",
            kind="index",
            archive_root=None,
        )


async def test_refresh_daily_skip_ingest_and_seed() -> None:
    cal = MagicMock()
    cal.default_as_of.return_value = date(2026, 9, 4)
    uni = MagicMock()
    uni.bootstrap_symbols = ["600519.SH"]
    mkt = MagicMock()
    mkt.benchmark_symbol = "000300.SH"
    with (
        patch("quantagent.data.ops.daily_refresh.TradingCalendar", return_value=cal),
        patch(
            "quantagent.data.ops.daily_refresh.load_universe_config",
            return_value=uni,
        ),
        patch(
            "quantagent.data.ops.daily_refresh.load_market_config",
            return_value=mkt,
        ),
        patch(
            "quantagent.data.ops.daily_refresh.seed_universe_snapshot",
            return_value={
                "code": "mvp_cn_50",
                "as_of": date(2026, 9, 4),
                "n_seeded": 1,
                "missing": ["x"],
            },
        ),
    ):
        result = await refresh_daily_market_data(
            as_of=date(2026, 9, 4),
            skip_ingest=True,
            skip_seed=False,
        )
    assert isinstance(result, DailyRefreshResult)
    assert result.price_rows == 0
    assert result.n_seeded == 1
    assert result.missing == ["x"]
    assert result.n_symbols == 1
