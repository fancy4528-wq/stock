"""Unit tests for real-data L1 panel helpers (no DB)."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.quant.evaluation.panel_loader import (
    VALUE_FACTOR_CODES,
    cast_panel_floats,
    codes_for_real_l1,
    export_l1_price_panel,
)
from quantagent.quant.features.base import FactorInput
from quantagent.quant.features.registry import ALL_FACTOR_CODES


def test_cast_panel_floats_decimal_to_f64() -> None:
    # Mirror Decimal columns returned by Postgres / Polars DB reads.
    df = pl.DataFrame(
        {
            "security_id": pl.Series([1], dtype=pl.Int64),
            "trade_date": [date(2024, 1, 2)],
            "close": pl.Series(["100.0000"], dtype=pl.Decimal(18, 4)),
            "open": pl.Series(["99.5000"], dtype=pl.Decimal(18, 4)),
            "volume": pl.Series([1_000_000], dtype=pl.Int64),
        }
    )
    out = cast_panel_floats(df)
    assert out.schema["close"] == pl.Float64
    assert out.schema["open"] == pl.Float64
    assert abs(float(out["close"][0]) - 100.0) < 1e-9


def test_codes_for_real_l1_skips_value_without_valuation() -> None:
    prices = pl.DataFrame(
        {
            "security_id": [1, 1],
            "trade_date": [date(2024, 1, 2), date(2024, 1, 3)],
            "close": [10.0, 10.1],
        }
    )
    data = FactorInput(prices=prices, as_of=date(2024, 1, 3))
    runnable, skipped = codes_for_real_l1(data)
    assert set(skipped) == VALUE_FACTOR_CODES
    assert set(runnable) | set(skipped) == set(ALL_FACTOR_CODES)
    assert "mom_20d" in runnable
    assert "ep_ttm" not in runnable


def test_codes_for_real_l1_keeps_value_when_pe_on_prices() -> None:
    prices = pl.DataFrame(
        {
            "security_id": [1],
            "trade_date": [date(2024, 1, 2)],
            "close": [10.0],
            "pe_ttm": [12.0],
            "pb": [2.0],
            "ps_ttm": [4.0],
        }
    )
    data = FactorInput(prices=prices, as_of=date(2024, 1, 2))
    runnable, skipped = codes_for_real_l1(data)
    assert skipped == []
    assert set(VALUE_FACTOR_CODES).issubset(runnable)


def test_export_l1_price_panel(tmp_path) -> None:
    prices = pl.DataFrame(
        {
            "security_id": [1],
            "trade_date": [date(2024, 1, 2)],
            "close": [10.0],
        }
    )
    data = FactorInput(prices=prices, as_of=date(2024, 1, 2))
    path = tmp_path / "panel.parquet"
    export_l1_price_panel(data, path)
    loaded = pl.read_parquet(path)
    assert loaded.height == 1
    assert "close" in loaded.columns
