"""Load normalized frames into PIT tables (UPSERT; never rewrite history versions)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from quantagent.data.normalizers.symbol import to_raw_digits
from quantagent.data.validators import ValidationContext, Validator, persist_rule_results
from quantagent.data.validators.report import ValidationReport
from quantagent.shared.config import get_settings
from quantagent.shared.errors import DataError, DataQualityError


def _infer_board(digits: str) -> str:
    if digits.startswith("68"):
        return "star"
    if digits.startswith("30"):
        return "gem"
    if digits.startswith(("43", "83", "87", "88", "92")):
        return "bse"
    return "main"


class PriceLoader:
    """UPSERT canonical price rows into ``price_daily`` (+ ensure ``security``)."""

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
            raise DataError("PriceLoader refused empty frame")

        check_date = target_date or date.today()
        batch_id = self._start_batch(
            source=source,
            dataset="price_daily",
            target_date=check_date,
            started_at=datetime.now(UTC),
            raw_path=str(raw_path) if raw_path else None,
        )
        try:
            if validate and report is None:
                report = Validator(self._engine).validate(
                    df,
                    "price_daily",
                    ValidationContext(
                        check_date=check_date,
                        batch_id=batch_id,
                        persist=False,
                    ),
                )
            elif report is not None and report.blocking:
                raise DataQualityError("precomputed report is blocking")
            if report is None:
                raise DataError("PriceLoader requires a ValidationReport when validate=False")

            with self._engine.begin() as conn:
                persist_rule_results(conn, report, batch_id=batch_id)
                id_map = self._ensure_securities(conn, df)
                suspect = report.suspect_keys()
                n = self._upsert_prices(
                    conn, df, id_map=id_map, suspect=suspect, source=source
                )

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

    def _ensure_securities(self, conn: Connection, df: pl.DataFrame) -> dict[str, int]:
        symbols = sorted(set(df["symbol"].to_list()))
        id_map: dict[str, int] = {}
        for symbol in symbols:
            digits = to_raw_digits(symbol)
            board = _infer_board(digits)
            sec_id = conn.execute(
                text(
                    """
                    INSERT INTO security (market, symbol, raw_symbol, name, board, currency)
                    VALUES ('CN', :symbol, :raw, :name, :board, 'CNY')
                    ON CONFLICT (market, symbol) DO UPDATE
                      SET raw_symbol = EXCLUDED.raw_symbol
                    RETURNING security_id
                    """
                ),
                {
                    "symbol": symbol,
                    "raw": digits,
                    "name": symbol,
                    "board": board,
                },
            ).scalar_one()
            id_map[symbol] = int(sec_id)
        return id_map

    def _upsert_prices(
        self,
        conn: Connection,
        df: pl.DataFrame,
        *,
        id_map: dict[str, int],
        suspect: set[str],
        source: str,
    ) -> int:
        rows = df.to_dicts()
        n = 0
        stmt = text(
            """
            INSERT INTO price_daily (
                security_id, trade_date, open, high, low, close, prev_close,
                volume, amount, turnover_rate,
                limit_up_px, limit_down_px, is_limit_up, is_limit_down, is_suspended,
                source, quality, ingested_at
            ) VALUES (
                :security_id, :trade_date, :open, :high, :low, :close, :prev_close,
                :volume, :amount, :turnover_rate,
                :limit_up_px, :limit_down_px, :is_limit_up, :is_limit_down, :is_suspended,
                :source, :quality, :ingested_at
            )
            ON CONFLICT (security_id, trade_date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                prev_close = EXCLUDED.prev_close,
                volume = EXCLUDED.volume,
                amount = EXCLUDED.amount,
                turnover_rate = EXCLUDED.turnover_rate,
                limit_up_px = EXCLUDED.limit_up_px,
                limit_down_px = EXCLUDED.limit_down_px,
                is_limit_up = EXCLUDED.is_limit_up,
                is_limit_down = EXCLUDED.is_limit_down,
                is_suspended = EXCLUDED.is_suspended,
                source = EXCLUDED.source,
                quality = EXCLUDED.quality,
                ingested_at = EXCLUDED.ingested_at
            """
        )
        now = datetime.now(UTC)
        for row in rows:
            symbol = row["symbol"]
            trade_date = row["trade_date"]
            key = f"{symbol}|{trade_date}"
            quality = "suspect" if key in suspect else "ok"
            conn.execute(
                stmt,
                {
                    "security_id": id_map[symbol],
                    "trade_date": trade_date,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "prev_close": row.get("prev_close"),
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                    "turnover_rate": row.get("turnover_rate"),
                    "limit_up_px": row.get("limit_up_px"),
                    "limit_down_px": row.get("limit_down_px"),
                    "is_limit_up": bool(row.get("is_limit_up") or False),
                    "is_limit_down": bool(row.get("is_limit_down") or False),
                    "is_suspended": bool(row.get("is_suspended") or False),
                    "source": row.get("source") or source,
                    "quality": quality,
                    "ingested_at": now,
                },
            )
            n += 1
        return n
