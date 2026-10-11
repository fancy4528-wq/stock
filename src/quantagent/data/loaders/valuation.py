"""Load normalized valuation rows into ``valuation_daily``."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from quantagent.data.normalizers.symbol import to_raw_digits
from quantagent.data.validators import persist_rule_results
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


class ValuationLoader:
    """UPSERT canonical valuation rows into ``valuation_daily``."""

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
            raise DataError("ValuationLoader refused empty frame")

        check_date = target_date or date.today()
        batch_id = self._start_batch(
            source=source,
            dataset="valuation_daily",
            target_date=check_date,
            started_at=datetime.now(UTC),
            raw_path=str(raw_path) if raw_path else None,
        )
        try:
            if validate and report is None:
                report = ValidationReport(
                    dataset="valuation_daily",
                    check_date=check_date,
                    results=[],
                )
            elif report is not None and report.blocking:
                raise DataQualityError("precomputed report is blocking")
            if report is None:
                report = ValidationReport(
                    dataset="valuation_daily",
                    check_date=check_date,
                    results=[],
                )

            with self._engine.begin() as conn:
                persist_rule_results(conn, report, batch_id=batch_id)
                id_map = self._ensure_securities(conn, df)
                n = self._upsert_valuations(conn, df, id_map=id_map, source=source)

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
        symbols = sorted({str(s) for s in df["symbol"].to_list() if s})
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

    def _upsert_valuations(
        self,
        conn: Connection,
        df: pl.DataFrame,
        *,
        id_map: dict[str, int],
        source: str,
    ) -> int:
        rows = df.to_dicts()
        stmt = text(
            """
            INSERT INTO valuation_daily (
                security_id, trade_date,
                market_cap, circ_market_cap,
                pe_ttm, pe_lyr, pb, ps_ttm, dividend_yield,
                source
            ) VALUES (
                :security_id, :trade_date,
                :market_cap, :circ_market_cap,
                :pe_ttm, :pe_lyr, :pb, :ps_ttm, :dividend_yield,
                :source
            )
            ON CONFLICT (security_id, trade_date) DO UPDATE SET
                market_cap = EXCLUDED.market_cap,
                circ_market_cap = EXCLUDED.circ_market_cap,
                pe_ttm = EXCLUDED.pe_ttm,
                pe_lyr = EXCLUDED.pe_lyr,
                pb = EXCLUDED.pb,
                ps_ttm = EXCLUDED.ps_ttm,
                dividend_yield = EXCLUDED.dividend_yield,
                source = EXCLUDED.source
            """
        )
        payload = [
            {
                "security_id": id_map[str(row["symbol"])],
                "trade_date": row["trade_date"],
                "market_cap": row.get("market_cap"),
                "circ_market_cap": row.get("circ_market_cap"),
                "pe_ttm": row.get("pe_ttm"),
                "pe_lyr": row.get("pe_lyr"),
                "pb": row.get("pb"),
                "ps_ttm": row.get("ps_ttm"),
                "dividend_yield": row.get("dividend_yield"),
                "source": source,
            }
            for row in rows
        ]
        if not payload:
            return 0
        conn.execute(stmt, payload)
        return len(payload)
