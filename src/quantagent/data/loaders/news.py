"""Load normalized news rows into ``news`` (idempotent upsert)."""

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


class NewsLoader:
    """UPSERT into ``news`` on (source, source_id) / (source, content_hash)."""

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
    ) -> dict[str, int | str | list[int]]:
        if df.is_empty():
            raise DataError("NewsLoader refused empty frame")

        check_date = target_date or date.today()
        dataset = "announcement" if source == "em_announce" else "news"
        batch_id = self._start_batch(
            source=source,
            dataset=dataset,
            target_date=check_date,
            started_at=datetime.now(UTC),
            raw_path=str(raw_path) if raw_path else None,
        )
        try:
            if validate and report is None:
                report = Validator(self._engine).validate(
                    df,
                    "news",
                    ValidationContext(
                        check_date=check_date,
                        batch_id=batch_id,
                        persist=False,
                    ),
                )
            elif report is not None and report.blocking:
                raise DataQualityError("precomputed report is blocking")
            if report is None:
                raise DataError("NewsLoader requires ValidationReport when validate=False")

            with self._engine.begin() as conn:
                persist_rule_results(conn, report, batch_id=batch_id)
                news_ids = self._upsert(conn, df)

            self._finish_batch(batch_id, status="success", row_count=len(news_ids))
            return {
                "batch_id": batch_id,
                "rows_loaded": len(news_ids),
                "news_ids": news_ids,
                "status": "success",
            }
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

    def _upsert(self, conn: Connection, df: pl.DataFrame) -> list[int]:
        stmt = text(
            """
            INSERT INTO news (
                source, source_id, url, title, body, published_at,
                lang, content_hash, raw_ref
            ) VALUES (
                :source, :source_id, :url, :title, :body, :published_at,
                :lang, :content_hash, :raw_ref
            )
            ON CONFLICT (source, source_id) DO UPDATE SET
                url = COALESCE(EXCLUDED.url, news.url),
                title = EXCLUDED.title,
                body = COALESCE(EXCLUDED.body, news.body),
                published_at = EXCLUDED.published_at,
                raw_ref = COALESCE(EXCLUDED.raw_ref, news.raw_ref)
            RETURNING news_id
            """
        )
        ids: list[int] = []
        for row in df.to_dicts():
            news_id = conn.execute(
                stmt,
                {
                    "source": str(row["source"]),
                    "source_id": str(row["source_id"]),
                    "url": row.get("url"),
                    "title": str(row["title"]),
                    "body": row.get("body"),
                    "published_at": row["published_at"],
                    "lang": str(row.get("lang") or "zh"),
                    "content_hash": str(row["content_hash"]),
                    "raw_ref": row.get("raw_ref"),
                },
            ).scalar_one()
            ids.append(int(news_id))
        return ids
