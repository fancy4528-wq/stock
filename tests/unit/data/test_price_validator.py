"""Unit tests for price validation rules."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from quantagent.data.validators import ValidationContext, Validator
from quantagent.data.validators.price import (
    rule_px_001_ohlc,
    rule_px_002_positive_prices,
    rule_px_003_nonneg_volume_amount,
    rule_px_008_vwap_band,
)
from quantagent.shared.errors import DataQualityError


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "600519.SH",
        "trade_date": date(2026, 9, 1),
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 104.0,
        "prev_close": 100.0,
        "volume": 1000,
        "amount": 102_000.0,
        "turnover_rate": 0.01,
        "source": "test",
    }
    base.update(overrides)
    return base


def test_px_001_detects_ohlc_break() -> None:
    df = pl.DataFrame([_row(high=90.0)])
    r = rule_px_001_ohlc(df)
    assert r.status == "fail"
    assert r.affected_count == 1


def test_px_002_rejects_non_positive() -> None:
    df = pl.DataFrame([_row(close=0.0)])
    r = rule_px_002_positive_prices(df)
    assert r.status == "fail"


def test_px_003_rejects_negative_volume() -> None:
    df = pl.DataFrame([_row(volume=-1)])
    r = rule_px_003_nonneg_volume_amount(df)
    assert r.status == "fail"


def test_px_008_warns_vwap_out_of_band() -> None:
    # amount/volume = 200, outside [99, 105]
    df = pl.DataFrame([_row(amount=200_000.0, volume=1000)])
    r = rule_px_008_vwap_band(df)
    assert r.status == "warn"
    assert r.level == "WARN"


def test_validator_blocks_on_error() -> None:
    df = pl.DataFrame([_row(high=50.0, low=60.0)])
    with pytest.raises(DataQualityError, match="PX_001"):
        Validator().validate(df, "price_daily", ValidationContext(persist=False))


def test_validator_passes_clean_frame() -> None:
    df = pl.DataFrame([_row()])
    report = Validator().validate(df, "price_daily", ValidationContext(persist=False))
    assert not report.blocking
    assert all(r.status == "pass" for r in report.results)
