"""Load canonical trading calendar rows into ``trading_calendar``."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from quantagent.data.validators import ValidationContext, Validator, persist_rule_results
from quantagent.data.validators.report import ValidationReport
from quantagent.shared.config import get_settings
from quantagent.shared.errors import DataError, DataQualityError


class CalendarLoader:
    """UPSERT dense calendar rows into ``trading_calendar``."""

    def __init__(self, engine: Engine | None = None) -> None:
        if engine is not None:
            self._engine = engine
        else:
            self._engine = create_engine(get_settings().database_url, pool_pre_ping=True)

    def load(
        self,
        df: pl.DataFrame,
        *,
        source: str,
        raw_path: Path | str | None = None,
        target_date: date | None = None,
        validate: bool = True,
        report: ValidationReport | None = None,
    ) -> dict[str, int | str]:
        if df.is_empty():
            raise DataError("CalendarLoader refused empty frame")

        check_date = target_date or date.today()
        batch_id = self._start_batch(
            source=source,
            dataset="trading_calendar",
            target_date=check_date,
            started_at=datetime.now(UTC),
            raw_path=str(raw_path) if raw_path else None,
        )
        try:
            if validate and report is None:
                report = Validator(self._engine).validate(
                    df,
                    "trading_calendar",
                    ValidationContext(
                        check_date=check_date,
                        batch_id=batch_id,
                        persist=False,
                    ),
                )
            elif report is not None and report.blocking:
                raise DataQualityError("precomputed report is blocking")
            if report is None:
                raise DataError("CalendarLoader requires a ValidationReport when validate=False")

            with self._engine.begin() as conn:
                persist_rule_results(conn, report, batch_id=batch_id)
                n = self._upsert(conn, df)

            self._finish_batch(batch_id, status="success", row_count=n)
            return {"batch_id": batch_id, "rows_loaded": n, "status": "success"}
        except Exception as exc:
            self._finish_batch(batch_id, status="failed", row_count=0, error=str(exc))
            raise

    def _start_batch(
        self,
        *,
        source: str,
        dataset: str,
        target_date: date,
        started_at: datetime,
        raw_path: str | None,
    ) -> int:
        with self._engine.begin() as conn:
            batch_id = conn.execute(
                text(
                    """
                    INSERT INTO ingest_batch (
                        source, dataset, target_date, started_at, status, raw_path
                    ) VALUES (
                        :source, :dataset, :target_date, :started_at, 'running', :raw_path
                    )
                    RETURNING batch_id
                    """
                ),
                {
                    "source": source,
                    "dataset": dataset,
                    "target_date": target_date,
                    "started_at": started_at,
                    "raw_path": raw_path,
                },
            ).scalar_one()
        return int(batch_id)

    def _finish_batch(
        self,
        batch_id: int,
        *,
        status: str,
        row_count: int,
        error: str | None = None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ingest_batch
                    SET finished_at = :finished_at,
                        status = :status,
                        row_count = :row_count,
                        error = :error
                    WHERE batch_id = :batch_id
                    """
                ),
                {
                    "batch_id": batch_id,
                    "finished_at": datetime.now(UTC),
                    "status": status,
                    "row_count": row_count,
                    "error": error,
                },
            )

    def _upsert(self, conn: Connection, df: pl.DataFrame) -> int:
        stmt = text(
            """
            INSERT INTO trading_calendar (
                market, trade_date, is_open, prev_trade_date, next_trade_date, note
            ) VALUES (
                :market, :trade_date, :is_open, :prev_trade_date, :next_trade_date, :note
            )
            ON CONFLICT (market, trade_date) DO UPDATE SET
                is_open = EXCLUDED.is_open,
                prev_trade_date = EXCLUDED.prev_trade_date,
                next_trade_date = EXCLUDED.next_trade_date,
                note = COALESCE(EXCLUDED.note, trading_calendar.note)
            """
        )
        n = 0
        for row in df.to_dicts():
            conn.execute(
                stmt,
                {
                    "market": row["market"],
                    "trade_date": row["trade_date"],
                    "is_open": bool(row["is_open"]),
                    "prev_trade_date": row.get("prev_trade_date"),
                    "next_trade_date": row.get("next_trade_date"),
                    "note": row.get("note"),
                },
            )
            n += 1
        return n
