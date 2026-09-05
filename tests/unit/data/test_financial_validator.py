"""Unit tests for financial validators."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.data.validators import ValidationContext, Validator
from quantagent.data.validators.financial import (
    rule_fin_001_balance_identity,
    rule_fin_002_announced_after_period,
    rule_fin_009_duplicate_revision_keys,
)
from quantagent.shared.errors import DataQualityError

CN = ZoneInfo("Asia/Shanghai")


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "600519.SH",
        "period_end": date(2024, 12, 31),
        "period_type": "FY",
        "announced_at": datetime(2025, 3, 30, 15, 0, tzinfo=CN),
        "report_type": "original",
        "revenue": 100.0,
        "operating_cost": 40.0,
        "gross_profit": 60.0,
        "operating_profit": 50.0,
        "net_profit": 40.0,
        "net_profit_attr": 39.0,
        "net_profit_deducted": 38.0,
        "eps": 1.0,
        "total_assets": 200.0,
        "total_liab": 80.0,
        "total_equity": 120.0,
        "equity_attr": 110.0,
        "cash_and_equiv": 10.0,
        "inventory": 5.0,
        "accounts_recv": 4.0,
        "goodwill": 1.0,
        "cfo": 30.0,
        "cfi": -10.0,
        "cff": -5.0,
        "capex": 8.0,
        "source": "test",
    }
    base.update(overrides)
    return base


def test_fin_001_detects_balance_break() -> None:
    df = pl.DataFrame([_row(total_assets=100.0, total_liab=10.0, total_equity=10.0)])
    r = rule_fin_001_balance_identity(df)
    assert r.status == "fail"


def test_fin_002_fatal_early_announce() -> None:
    df = pl.DataFrame(
        [_row(announced_at=datetime(2024, 1, 1, 15, 0, tzinfo=CN))]
    )
    r = rule_fin_002_announced_after_period(df)
    assert r.status == "fail"
    assert r.level == "FATAL"


def test_fin_009_duplicate_keys() -> None:
    df = pl.DataFrame([_row(), _row()])
    r = rule_fin_009_duplicate_revision_keys(df)
    assert r.status == "fail"


def test_validator_blocks_on_fin_fatal() -> None:
    df = pl.DataFrame(
        [_row(announced_at=datetime(2024, 1, 1, 15, 0, tzinfo=CN))]
    )
    with pytest.raises(DataQualityError, match="FIN_002"):
        Validator().validate(
            df, "financial_statement", ValidationContext(persist=False)
        )
