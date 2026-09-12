"""Unit tests for adjust-factor normalizer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.adjust import AdjustNormalizer, trade_date_eod

CN_TZ = ZoneInfo("Asia/Shanghai")


def test_trade_date_eod_shanghai() -> None:
    dt = trade_date_eod(date(2026, 9, 1))
    assert dt == datetime(2026, 9, 1, 15, 0, tzinfo=CN_TZ)


def test_baostock_adjust_normalizer() -> None:
    raw = pl.DataFrame(
        {
            "code": ["sh.600519"],
            "dividOperateDate": ["2026-06-15"],
            "foreAdjustFactor": ["1.234567"],
            "backAdjustFactor": ["0.876543"],
            "adjustFactor": ["0.876543"],
        }
    )
    batch = RawBatch(
        batch_id=1,
        source="baostock",
        dataset="adjust_factor",
        target_date=date(2026, 6, 15),
        raw_path=Path("dummy.parquet"),
        row_count=1,
        collected_at=datetime(2026, 6, 15, tzinfo=UTC),
        meta={"symbols": ["600519.SH"]},
    )
    out = AdjustNormalizer().normalize(batch, raw)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["symbol"] == "600519.SH"
    assert row["trade_date"] == date(2026, 6, 15)
    assert row["factor_qfq"] == pytest.approx(1.234567)  # type: ignore[name-defined]
    assert row["factor_hfq"] == pytest.approx(0.876543)  # type: ignore[name-defined]
    assert row["source"] == "baostock"
    assert row["announced_at"] == trade_date_eod(date(2026, 6, 15))
