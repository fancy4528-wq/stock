"""Unit tests for Calendar / Industry / Financial loader guards."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from quantagent.data.loaders.calendar import CalendarLoader
from quantagent.data.loaders.financial import FinancialLoader
from quantagent.data.loaders.financial import _infer_board as fin_board
from quantagent.data.loaders.industry import IndustryLoader
from quantagent.data.loaders.industry import _infer_board as ind_board
from quantagent.data.validators.report import RuleResult, ValidationReport
from quantagent.shared.errors import DataError, DataQualityError


def _blocking() -> ValidationReport:
    return ValidationReport(
        dataset="x",
        check_date=date(2026, 1, 1),
        results=[RuleResult(code="X", level="FATAL", status="fail", detail="bad")],
    )


def test_board_helpers() -> None:
    assert fin_board("688001") == "star"
    assert ind_board("300001") == "gem"
    assert fin_board("920001") == "bse"
    assert ind_board("600000") == "main"


def test_calendar_loader_empty_and_blocking() -> None:
    loader = CalendarLoader(engine=MagicMock())
    with pytest.raises(DataError, match="empty"):
        loader.load(pl.DataFrame(), source="akshare")

    with patch.object(loader, "_start_batch", return_value=1), patch.object(
        loader, "_finish_batch"
    ):
        with pytest.raises(DataQualityError, match="blocking"):
            loader.load(
                pl.DataFrame(
                    {
                        "market": ["CN"],
                        "trade_date": [date(2026, 1, 1)],
                        "is_open": [True],
                    }
                ),
                source="akshare",
                validate=False,
                report=_blocking(),
            )


def test_calendar_upsert() -> None:
    loader = CalendarLoader(engine=MagicMock())
    conn = MagicMock()
    df = pl.DataFrame(
        {
            "market": ["CN", "CN"],
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "is_open": [True, False],
            "prev_trade_date": [None, date(2026, 1, 1)],
            "next_trade_date": [date(2026, 1, 2), None],
            "note": [None, "holiday"],
        }
    )
    assert loader._upsert(conn, df) == 2


def test_industry_loader_empty_and_blocking() -> None:
    loader = IndustryLoader(engine=MagicMock())
    with pytest.raises(DataError, match="empty"):
        loader.load(pl.DataFrame(), source="akshare")

    with patch.object(loader, "_start_batch", return_value=1), patch.object(
        loader, "_finish_batch"
    ):
        with pytest.raises(DataQualityError, match="blocking"):
            loader.load(
                pl.DataFrame({"record_type": ["industry"]}),
                source="akshare",
                validate=False,
                report=_blocking(),
            )
        with pytest.raises(DataError, match="ValidationReport"):
            loader.load(
                pl.DataFrame({"record_type": ["industry"]}),
                source="akshare",
                validate=False,
                report=None,
            )


def test_financial_loader_empty_and_blocking() -> None:
    loader = FinancialLoader(engine=MagicMock())
    with pytest.raises(DataError, match="empty"):
        loader.load(pl.DataFrame(), source="akshare")

    with patch.object(loader, "_start_batch", return_value=1), patch.object(
        loader, "_finish_batch"
    ):
        with pytest.raises(DataQualityError, match="blocking"):
            loader.load(
                pl.DataFrame({"symbol": ["600519.SH"]}),
                source="akshare",
                validate=False,
                report=_blocking(),
            )
