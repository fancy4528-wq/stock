"""Integration: validate + load price_daily, then PIT readback."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.repository.pit import PITRepository
from quantagent.data.loaders import PriceLoader
from quantagent.shared.errors import DataQualityError

pytestmark = pytest.mark.integration


def _clean_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "trade_date": [date(2026, 9, 1), date(2026, 9, 2)],
            "open": [100.0, 101.0],
            "high": [105.0, 106.0],
            "low": [99.0, 100.0],
            "close": [104.0, 105.0],
            "prev_close": [100.0, 104.0],
            "volume": [1_000_000, 1_100_000],
            "amount": [104_000_000.0, 115_000_000.0],
            "turnover_rate": [0.01, 0.011],
            "source": ["baostock", "baostock"],
        }
    )


def test_price_loader_upsert_and_pit_read(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    # Ensure W3 tables exist (migration may have been applied separately).
    with engine.begin() as conn:
        conn.execute(text("SELECT 1 FROM ingest_batch LIMIT 0"))
        conn.execute(text("SELECT 1 FROM data_quality_check LIMIT 0"))

    loader = PriceLoader(engine)
    result = loader.load(
        _clean_frame(),
        source="baostock",
        target_date=date(2026, 9, 2),
    )
    assert result["rows_loaded"] == 2
    assert result["status"] == "success"

    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM price_daily")).scalar_one()
        assert int(n) == 2
        dq = conn.execute(
            text("SELECT COUNT(*) FROM data_quality_check WHERE batch_id = :b"),
            {"b": result["batch_id"]},
        ).scalar_one()
        assert int(dq) >= 1
        status = conn.execute(
            text("SELECT status FROM ingest_batch WHERE batch_id = :b"),
            {"b": result["batch_id"]},
        ).scalar_one()
        assert status == "success"

    repo = PITRepository(engine)
    prices = repo.get_prices(
        ["600519.SH"],
        as_of=date(2026, 9, 2),
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        adjust="qfq",
    )
    assert prices.height == 2


def test_price_loader_rejects_bad_ohlc(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    bad = _clean_frame().with_columns(pl.lit(50.0).alias("high"))
    loader = PriceLoader(engine)
    with pytest.raises(DataQualityError):
        loader.load(bad, source="test", target_date=date(2026, 9, 2))

    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM price_daily")).scalar_one()
        assert int(n) == 0
        failed = conn.execute(
            text("SELECT COUNT(*) FROM ingest_batch WHERE status = 'failed'")
        ).scalar_one()
        assert int(failed) >= 1
