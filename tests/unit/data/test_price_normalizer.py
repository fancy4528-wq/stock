"""Unit tests for PriceNormalizer and Parquet archive replay."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from quantagent.data.archive.parquet import ParquetArchive, load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.price import CANONICAL_PRICE_COLUMNS, PriceNormalizer


def _akshare_raw() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "日期": [date(2024, 1, 2), date(2024, 1, 3)],
            "股票代码": ["600519", "600519"],
            "开盘": [1680.0, 1690.0],
            "收盘": [1688.0, 1700.0],
            "最高": [1695.0, 1710.0],
            "最低": [1670.0, 1685.0],
            "成交量": [1000, 2000],  # 手
            "成交额": [168_800_000.0, 340_000_000.0],
            "换手率": [0.50, 1.00],  # %
            "_request_symbol": ["600519", "600519"],
        }
    )


def _baostock_raw() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "code": ["sh.600519", "sh.600519"],
            "open": ["1680.000", "1690.000"],
            "high": ["1695.000", "1710.000"],
            "low": ["1670.000", "1685.000"],
            "close": ["1688.000", "1700.000"],
            "preclose": ["1675.000", "1688.000"],
            "volume": ["100000", "200000"],  # 股
            "amount": ["168800000.000", "340000000.000"],
            "turn": ["0.500000", "1.000000"],
        }
    )


def test_normalize_akshare_units_and_symbol(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    batch = archive.write(
        _akshare_raw(),
        source="akshare",
        dataset="price_daily",
        target_date=date(2024, 1, 3),
        meta={"symbols": ["600519.SH"], "start": "2024-01-02", "end": "2024-01-03"},
        collected_at=datetime(2024, 1, 3, 8, 0, tzinfo=UTC),
    )
    out = PriceNormalizer().normalize(batch)
    assert out.columns == CANONICAL_PRICE_COLUMNS
    assert out["symbol"].to_list() == ["600519.SH", "600519.SH"]
    assert out["volume"].to_list() == [100_000, 200_000]
    assert out["turnover_rate"].to_list() == pytest.approx([0.005, 0.01])
    assert out["source"].to_list() == ["akshare", "akshare"]


def test_normalize_baostock(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    batch = archive.write(
        _baostock_raw(),
        source="baostock",
        dataset="price_daily",
        target_date=date(2024, 1, 3),
        meta={"symbols": ["600519.SH"]},
        collected_at=datetime(2024, 1, 3, 8, 0, tzinfo=UTC),
    )
    out = PriceNormalizer().normalize(batch)
    assert out["symbol"].to_list() == ["600519.SH", "600519.SH"]
    assert out["volume"].to_list() == [100_000, 200_000]
    assert out["prev_close"].to_list() == [1675.0, 1688.0]
    assert out["turnover_rate"].to_list() == pytest.approx([0.005, 0.01])


def test_replay_from_archive(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    batch = archive.write(
        _akshare_raw(),
        source="akshare",
        dataset="price_daily",
        target_date=date(2024, 1, 3),
        meta={"symbols": ["600519.SH"]},
        collected_at=datetime(2024, 1, 3, 8, 0, tzinfo=UTC),
    )
    df, loaded = load_raw_batch(batch.raw_path)
    assert loaded.source == "akshare"
    assert df.height == 2
    replayed = PriceNormalizer().normalize_from_archive(batch.raw_path)
    assert replayed.height == 2


def test_raw_batch_model() -> None:
    batch = RawBatch(
        batch_id=1,
        source="akshare",
        dataset="price_daily",
        target_date=date(2024, 1, 2),
        raw_path=Path("data/raw/x.parquet"),
        row_count=0,
        collected_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    assert batch.meta == {}
