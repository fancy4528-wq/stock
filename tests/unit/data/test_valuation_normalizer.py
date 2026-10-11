"""Unit tests for valuation normalizer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.valuation import ValuationNormalizer


def test_baostock_valuation_normalizer() -> None:
    raw = pl.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "code": ["sh.600519", "sh.600519"],
            "peTTM": ["20.5", ""],
            "pbMRQ": ["8.1", "8.2"],
            "psTTM": ["10.0", "10.1"],
        }
    )
    batch = RawBatch(
        batch_id=1,
        source="baostock",
        dataset="valuation_daily",
        target_date=date(2024, 1, 3),
        raw_path=Path("dummy.parquet"),
        row_count=2,
        collected_at=datetime(2024, 1, 3, tzinfo=UTC),
        meta={"symbols": ["600519.SH"]},
    )
    out = ValuationNormalizer().normalize(batch, raw)
    assert out.height == 2
    assert out["symbol"].to_list() == ["600519.SH", "600519.SH"]
    assert float(out["pe_ttm"][0]) == pytest.approx(20.5)
    assert out["pe_ttm"][1] is None
    assert float(out["pb"][1]) == pytest.approx(8.2)
    assert float(out["ps_ttm"][0]) == pytest.approx(10.0)
