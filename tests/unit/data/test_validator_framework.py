"""Extra Validator framework coverage."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from quantagent.data.validators import ValidationContext, Validator, persist_rule_results
from quantagent.data.validators.report import RuleResult, ValidationReport
from quantagent.shared.errors import DataQualityError


def test_validator_unknown_dataset() -> None:
    with pytest.raises(DataQualityError, match="No validator"):
        Validator().validate(pl.DataFrame({"a": [1]}), "unknown", ValidationContext(persist=False))


def test_validator_fatal_notifies() -> None:
    fatal = RuleResult(code="PX_X", level="FATAL", status="fail", detail="boom")
    with (
        patch("quantagent.data.validators._invoke_rule", return_value=fatal),
        patch("quantagent.data.validators.notify_data_quality_fatal") as notify,
        pytest.raises(DataQualityError, match="PX_X"),
    ):
        Validator().validate(
            pl.DataFrame({"symbol": ["x"]}),
            "price_daily",
            ValidationContext(persist=False, extra={"run_id": "r1"}),
        )
    notify.assert_called_once()


def test_persist_rule_results() -> None:
    conn = MagicMock()
    report = ValidationReport(
        dataset="price_daily",
        check_date=date(2026, 1, 1),
        results=[
            RuleResult(code="A", level="WARN", status="pass", detail="ok", affected_count=0),
            RuleResult(
                code="B",
                level="ERROR",
                status="fail",
                detail="bad",
                affected_count=2,
                expected={"x": 1},
                actual={"y": 2},
            ),
        ],
    )
    persist_rule_results(conn, report, batch_id=9)
    assert conn.execute.call_count == 2
