"""Unit tests for dual-source price attach + PX_009."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from quantagent.data.validators import ValidationContext, Validator
from quantagent.data.validators.price import rule_px_009_dual_source_price
from quantagent.data.validators.price_dual import attach_peer_closes
from quantagent.shared.errors import DataQualityError


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "600519.SH",
        "trade_date": date(2026, 9, 1),
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 100.0,
        "prev_close": 100.0,
        "volume": 1000,
        "amount": 100_000.0,
        "turnover_rate": 0.01,
        "source": "akshare",
    }
    base.update(overrides)
    return base


def test_attach_peer_closes_joins_on_symbol_date() -> None:
    primary = pl.DataFrame([_row(close=100.0)])
    peer = pl.DataFrame([_row(close=100.2, source="baostock")])
    out = attach_peer_closes(primary, peer)
    assert out["close_peer"][0] == pytest.approx(100.2)


def test_px_009_fails_on_big_mismatch() -> None:
    primary = pl.DataFrame([_row(close=100.0)])
    peer = pl.DataFrame([_row(close=102.0, source="baostock")])
    dual = attach_peer_closes(primary, peer)
    result = rule_px_009_dual_source_price(dual)
    assert result.status == "fail"
    assert result.code == "PX_009"


def test_validator_blocks_on_dual_mismatch() -> None:
    primary = pl.DataFrame([_row(close=100.0)])
    peer = pl.DataFrame([_row(close=102.0, source="baostock")])
    dual = attach_peer_closes(primary, peer)
    with pytest.raises(DataQualityError, match="PX_009"):
        Validator().validate(dual, "price_daily", ValidationContext(persist=False))
