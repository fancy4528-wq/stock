"""Load normalized financial rows into ``financial_statement`` (append-only revisions)."""

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


_FIN_FIELDS = (
    "revenue",
    "operating_cost",
    "gross_profit",
    "operating_profit",
    "net_profit",
    "net_profit_attr",
    "net_profit_deducted",
    "eps",
    "total_assets",
    "total_liab",
    "total_equity",
    "equity_attr",
    "cash_and_equiv",
    "inventory",
    "accounts_recv",
    "goodwill",
    "cfo",
    "cfi",
    "cff",
    "capex",
)


class FinancialLoader:
    """INSERT financial_statement rows; bump revision on restatement, never UPDATE."""

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
            raise DataError("FinancialLoader refused empty frame")

        check_date = target_date or date.today()
        batch_id = self._start_batch(
            source=source,
            dataset="financial_statement",
            target_date=check_date,
            started_at=datetime.now(UTC),
            raw_path=str(raw_path) if raw_path else None,
        )
        try:
            if validate and report is None:
                report = Validator(self._engine).validate(
                    df,
                    "financial_statement",
                    ValidationContext(
                        check_date=check_date,
                        batch_id=batch_id,
                        persist=False,
                    ),
                )
            elif report is not None and report.blocking:
                raise DataQualityError("precomputed report is blocking")
            if report is None:
                raise DataError("FinancialLoader requires ValidationReport when validate=False")

            with self._engine.begin() as conn:
                persist_rule_results(conn, report, batch_id=batch_id)
                id_map = self._ensure_securities(conn, df)
                n = self._insert_statements(conn, df, id_map=id_map, source=source)

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

    def _insert_statements(
        self,
        conn: Connection,
        df: pl.DataFrame,
        *,
        id_map: dict[str, int],
        source: str,
    ) -> int:
        insert_stmt = text(
            """
            INSERT INTO financial_statement (
                security_id, period_end, period_type, revision, announced_at, report_type,
                revenue, operating_cost, gross_profit, operating_profit, net_profit,
                net_profit_attr, net_profit_deducted, eps,
                total_assets, total_liab, total_equity, equity_attr, cash_and_equiv,
                inventory, accounts_recv, goodwill,
                cfo, cfi, cff, capex,
                source, quality, ingested_at
            ) VALUES (
                :security_id, :period_end, :period_type, :revision, :announced_at, :report_type,
                :revenue, :operating_cost, :gross_profit, :operating_profit, :net_profit,
                :net_profit_attr, :net_profit_deducted, :eps,
                :total_assets, :total_liab, :total_equity, :equity_attr, :cash_and_equiv,
                :inventory, :accounts_recv, :goodwill,
                :cfo, :cfi, :cff, :capex,
                :source, :quality, :ingested_at
            )
            """
        )
        now = datetime.now(UTC)
        n = 0
        for row in df.to_dicts():
            sid = id_map[row["symbol"]]
            period_end = row["period_end"]
            period_type = row["period_type"]
            announced_at = row["announced_at"]

            existing = conn.execute(
                text(
                    """
                    SELECT revision, announced_at, net_profit, revenue, total_assets
                    FROM financial_statement
                    WHERE security_id = :sid
                      AND period_end = :period_end
                      AND period_type = :period_type
                    ORDER BY revision DESC
                    """
                ),
                {"sid": sid, "period_end": period_end, "period_type": period_type},
            ).mappings().all()

            if existing:
                # Idempotent: same announced_at already stored → skip.
                if any(r["announced_at"] == announced_at for r in existing):
                    continue
                latest = existing[0]
                same_nums = (
                    self._approx_eq(latest["net_profit"], row.get("net_profit"))
                    and self._approx_eq(latest["revenue"], row.get("revenue"))
                    and self._approx_eq(latest["total_assets"], row.get("total_assets"))
                )
                if same_nums and latest["announced_at"] >= announced_at:
                    continue
                revision = int(latest["revision"]) + 1
                report_type = "restated"
            else:
                revision = 1
                report_type = row.get("report_type") or "original"

            params = {
                "security_id": sid,
                "period_end": period_end,
                "period_type": period_type,
                "revision": revision,
                "announced_at": announced_at,
                "report_type": report_type,
                "source": row.get("source") or source,
                "quality": "ok",
                "ingested_at": now,
            }
            for field in _FIN_FIELDS:
                params[field] = row.get(field)
            conn.execute(insert_stmt, params)
            n += 1
        return n

    @staticmethod
    def _approx_eq(a: object, b: object, tol: float = 1e-2) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        try:
            return abs(float(a) - float(b)) <= tol  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
