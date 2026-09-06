"""Dataset validators — check and mark only; never mutate values."""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
from sqlalchemy import Connection, bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from quantagent.data.validators.calendar import CALENDAR_RULES
from quantagent.data.validators.financial import FINANCIAL_STATEMENT_RULES
from quantagent.data.validators.industry import INDUSTRY_RULES
from quantagent.data.validators.price import PRICE_DAILY_RULES
from quantagent.data.validators.report import ValidationReport
from quantagent.shared.config import get_settings
from quantagent.shared.errors import DataQualityError

__all__ = [
    "ValidationContext",
    "Validator",
    "persist_rule_results",
]


class ValidationContext:
    """Optional extras for cross-batch / calendar-aware rules."""

    def __init__(
        self,
        *,
        check_date: date | None = None,
        batch_id: int | None = None,
        persist: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.check_date = check_date or date.today()
        self.batch_id = batch_id
        self.persist = persist
        self.extra = extra or {}


class Validator:
    """Run dataset rules; optionally persist to ``data_quality_check``."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def _engine_or_default(self) -> Engine:
        if self._engine is not None:
            return self._engine
        return create_engine(get_settings().database_url, pool_pre_ping=True)

    def validate(
        self,
        df: pl.DataFrame,
        dataset: str,
        ctx: ValidationContext | None = None,
    ) -> ValidationReport:
        context = ctx or ValidationContext(persist=False)
        if dataset == "price_daily":
            rules = PRICE_DAILY_RULES
        elif dataset == "financial_statement":
            rules = FINANCIAL_STATEMENT_RULES
        elif dataset == "security_industry":
            rules = INDUSTRY_RULES
        elif dataset == "trading_calendar":
            rules = CALENDAR_RULES
        else:
            raise DataQualityError(f"No validator registered for dataset={dataset!r}")

        results = [rule(df) for rule in rules]
        report = ValidationReport(
            dataset=dataset,
            check_date=context.check_date,
            results=results,
        )

        if context.persist:
            with self._engine_or_default().begin() as conn:
                persist_rule_results(conn, report, batch_id=context.batch_id)

        if report.has_fatal:
            fatal = next(r for r in report.results if r.failed and r.level == "FATAL")
            raise DataQualityError(f"{fatal.code}: {fatal.detail}")
        if report.has_error:
            err = next(r for r in report.results if r.failed and r.level == "ERROR")
            raise DataQualityError(f"{err.code}: {err.detail}")
        return report


def persist_rule_results(
    conn: Connection,
    report: ValidationReport,
    *,
    batch_id: int | None,
) -> None:
    """Persist within an existing transaction (used by Loader)."""
    stmt = text(
        """
        INSERT INTO data_quality_check (
            check_date, dataset, rule_code, status,
            expected, actual, affected_count, detail, batch_id
        ) VALUES (
            :check_date, :dataset, :rule_code, :status,
            :expected, :actual, :affected_count, :detail, :batch_id
        )
        """
    ).bindparams(
        bindparam("expected", type_=JSONB),
        bindparam("actual", type_=JSONB),
    )
    for r in report.results:
        conn.execute(
            stmt,
            {
                "check_date": report.check_date,
                "dataset": report.dataset,
                "rule_code": r.code,
                "status": r.status,
                "expected": r.expected,
                "actual": r.actual,
                "affected_count": r.affected_count,
                "detail": r.detail,
                "batch_id": batch_id,
            },
        )
