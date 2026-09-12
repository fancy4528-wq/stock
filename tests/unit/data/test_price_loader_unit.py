"""Unit tests for PriceLoader (mocked engine / connection)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from quantagent.data.loaders.price import PriceLoader, _infer_board
from quantagent.data.validators.report import RuleResult, ValidationReport
from quantagent.shared.errors import DataError, DataQualityError


def test_infer_board() -> None:
    assert _infer_board("688001") == "star"
    assert _infer_board("300001") == "gem"
    assert _infer_board("430001") == "bse"
    assert _infer_board("830001") == "bse"
    assert _infer_board("600519") == "main"


def _price_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600519.SH", "300750.SZ"],
            "trade_date": [date(2026, 9, 1), date(2026, 9, 1)],
            "open": [100.0, 50.0],
            "high": [105.0, 51.0],
            "low": [99.0, 49.0],
            "close": [104.0, 50.5],
            "prev_close": [100.0, 50.0],
            "volume": [1_000_000, 2_000_000],
            "amount": [104_000_000.0, 100_000_000.0],
            "turnover_rate": [0.01, 0.02],
            "source": ["baostock", "baostock"],
            "limit_up_px": [110.0, 55.0],
            "limit_down_px": [90.0, 45.0],
            "is_limit_up": [False, False],
            "is_limit_down": [False, False],
            "is_suspended": [False, False],
        }
    )


def test_load_refuses_empty() -> None:
    loader = PriceLoader(engine=MagicMock())
    with pytest.raises(DataError, match="empty"):
        loader.load(pl.DataFrame(), source="baostock")


def test_load_blocking_precomputed_report() -> None:
    loader = PriceLoader(engine=MagicMock())
    with patch.object(loader, "_start_batch", return_value=1):
        with patch.object(loader, "_finish_batch") as finish:
            report = ValidationReport(
                dataset="price_daily",
                check_date=date(2026, 9, 1),
                results=[
                    RuleResult(
                        code="X",
                        level="FATAL",
                        status="fail",
                        detail="bad",
                    )
                ],
            )
            with pytest.raises(DataQualityError, match="blocking"):
                loader.load(
                    _price_frame(),
                    source="baostock",
                    validate=False,
                    report=report,
                )
            finish.assert_called()
            assert finish.call_args.kwargs["status"] == "failed"


def test_load_requires_report_when_validate_false() -> None:
    loader = PriceLoader(engine=MagicMock())
    with patch.object(loader, "_start_batch", return_value=1):
        with patch.object(loader, "_finish_batch"):
            with pytest.raises(DataError, match="ValidationReport"):
                loader.load(_price_frame(), source="baostock", validate=False, report=None)


def test_ensure_securities_and_upsert() -> None:
    loader = PriceLoader(engine=MagicMock())
    conn = MagicMock()
    conn.execute.return_value.scalar_one.side_effect = [11, 22]
    id_map = loader._ensure_securities(conn, _price_frame())
    assert id_map == {"300750.SZ": 11, "600519.SH": 22}

    n = loader._upsert_prices(
        conn,
        _price_frame(),
        id_map={"600519.SH": 1, "300750.SZ": 2},
        suspect={"600519.SH|2026-09-01"},
        source="baostock",
    )
    assert n == 2
    # Upserts iterate frame order: first row is 600519.SH and is suspect.
    first_params = conn.execute.call_args_list[-2][0][1]
    assert first_params["quality"] == "suspect"
    second_params = conn.execute.call_args_list[-1][0][1]
    assert second_params["quality"] == "ok"


def test_load_success_with_precomputed_report() -> None:
    loader = PriceLoader(engine=MagicMock())
    report = ValidationReport(
        dataset="price_daily",
        check_date=date(2026, 9, 1),
        results=[RuleResult(code="OK", level="WARN", status="pass", detail="ok")],
    )
    begin_ctx = MagicMock()
    conn = MagicMock()
    begin_ctx.__enter__.return_value = conn
    begin_ctx.__exit__.return_value = False
    loader._engine.begin.return_value = begin_ctx

    with (
        patch.object(loader, "_start_batch", return_value=42),
        patch.object(loader, "_finish_batch") as finish,
        patch("quantagent.data.loaders.price.persist_rule_results"),
        patch.object(loader, "_ensure_securities", return_value={"600519.SH": 1, "300750.SZ": 2}),
        patch.object(loader, "_upsert_prices", return_value=2),
    ):
        out = loader.load(
            _price_frame(),
            source="baostock",
            validate=False,
            report=report,
            target_date=date(2026, 9, 1),
        )
    assert out == {"batch_id": 42, "rows_loaded": 2, "status": "success"}
    finish.assert_called_once_with(42, status="success", row_count=2)
