"""Load normalized industry taxonomy + security memberships (interval-valid)."""

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


class IndustryLoader:
    """UPSERT ``industry`` nodes and maintain ``security_industry`` intervals."""

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
        snapshot_date: date | None = None,
    ) -> dict[str, int | str]:
        if df.is_empty():
            raise DataError("IndustryLoader refused empty frame")

        check_date = target_date or date.today()
        snap = snapshot_date or check_date
        batch_id = self._start_batch(
            source=source,
            dataset="security_industry",
            target_date=check_date,
            started_at=datetime.now(UTC),
            raw_path=str(raw_path) if raw_path else None,
        )
        try:
            if validate and report is None:
                report = Validator(self._engine).validate(
                    df,
                    "security_industry",
                    ValidationContext(
                        check_date=check_date,
                        batch_id=batch_id,
                        persist=False,
                    ),
                )
            elif report is not None and report.blocking:
                raise DataQualityError("precomputed report is blocking")
            if report is None:
                raise DataError("IndustryLoader requires ValidationReport when validate=False")

            industries = df.filter(pl.col("record_type") == "industry")
            memberships = df.filter(pl.col("record_type") == "membership")

            with self._engine.begin() as conn:
                persist_rule_results(conn, report, batch_id=batch_id)
                tax_map = self._ensure_taxonomies(conn, df)
                n_ind = self._upsert_industries(conn, industries, tax_map=tax_map)
                if memberships.is_empty():
                    id_map: dict[str, int] = {}
                else:
                    id_map = self._ensure_securities(conn, memberships)
                n_mem = self._apply_memberships(
                    conn,
                    memberships,
                    tax_map=tax_map,
                    id_map=id_map,
                    source=source,
                    snapshot_date=snap,
                )

            total = n_ind + n_mem
            self._finish_batch(batch_id, status="success", row_count=total)
            return {
                "batch_id": batch_id,
                "rows_loaded": total,
                "industries_upserted": n_ind,
                "memberships_applied": n_mem,
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

    def _ensure_taxonomies(self, conn: Connection, df: pl.DataFrame) -> dict[str, int]:
        codes = sorted({str(c) for c in df["taxonomy_code"].to_list() if c is not None})
        out: dict[str, int] = {}
        for code in codes:
            tax_id = conn.execute(
                text(
                    """
                    INSERT INTO industry_taxonomy (code, name, market, levels)
                    VALUES (:code, :name, 'CN', 3)
                    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                    RETURNING taxonomy_id
                    """
                ),
                {"code": code, "name": "申万行业分类 2021" if code == "sw_2021" else code},
            ).scalar_one()
            out[code] = int(tax_id)
        return out

    def _upsert_industries(
        self,
        conn: Connection,
        df: pl.DataFrame,
        *,
        tax_map: dict[str, int],
    ) -> int:
        if df.is_empty():
            return 0
        n = 0
        stmt = text(
            """
            INSERT INTO industry (taxonomy_id, code, name, level, parent_code)
            VALUES (:taxonomy_id, :code, :name, :level, :parent_code)
            ON CONFLICT (taxonomy_id, code) DO UPDATE SET
                name = EXCLUDED.name,
                level = EXCLUDED.level,
                parent_code = EXCLUDED.parent_code
            """
        )
        for row in df.to_dicts():
            tax = str(row["taxonomy_code"])
            conn.execute(
                stmt,
                {
                    "taxonomy_id": tax_map[tax],
                    "code": str(row["industry_code"]),
                    "name": str(row["industry_name"]),
                    "level": int(row["level"]),
                    "parent_code": row.get("parent_code"),
                },
            )
            n += 1
        return n

    def _ensure_securities(self, conn: Connection, df: pl.DataFrame) -> dict[str, int]:
        symbols = sorted({str(s) for s in df["symbol"].to_list() if s is not None})
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

    def _industry_id(
        self,
        conn: Connection,
        *,
        taxonomy_id: int,
        industry_code: str,
    ) -> int:
        ind_id = conn.execute(
            text(
                """
                SELECT industry_id FROM industry
                WHERE taxonomy_id = :taxonomy_id AND code = :code
                """
            ),
            {"taxonomy_id": taxonomy_id, "code": industry_code},
        ).scalar_one_or_none()
        if ind_id is None:
            raise DataError(f"industry node missing: taxonomy={taxonomy_id} code={industry_code}")
        return int(ind_id)

    def _apply_memberships(
        self,
        conn: Connection,
        df: pl.DataFrame,
        *,
        tax_map: dict[str, int],
        id_map: dict[str, int],
        source: str,
        snapshot_date: date,
    ) -> int:
        if df.is_empty():
            return 0

        n = 0
        now = datetime.now(UTC)
        for row in df.to_dicts():
            symbol = str(row["symbol"])
            security_id = id_map[symbol]
            taxonomy_id = tax_map[str(row["taxonomy_code"])]
            industry_id = self._industry_id(
                conn,
                taxonomy_id=taxonomy_id,
                industry_code=str(row["industry_code"]),
            )
            level = int(row["level"])
            valid_from = row["valid_from"]
            if not isinstance(valid_from, date):
                valid_from = date.fromisoformat(str(valid_from)[:10])
            row_source = str(row.get("source") or source)

            open_rows = conn.execute(
                text(
                    """
                    SELECT si.industry_id, si.valid_from, i.level
                    FROM security_industry si
                    JOIN industry i ON i.industry_id = si.industry_id
                    WHERE si.security_id = :security_id
                      AND i.taxonomy_id = :taxonomy_id
                      AND i.level = :level
                      AND si.valid_to IS NULL
                    ORDER BY si.valid_from DESC
                    """
                ),
                {
                    "security_id": security_id,
                    "taxonomy_id": taxonomy_id,
                    "level": level,
                },
            ).mappings().all()

            same_open = next((r for r in open_rows if int(r["industry_id"]) == industry_id), None)
            if same_open is not None:
                continue

            for open_row in open_rows:
                close_to = snapshot_date
                open_from = open_row["valid_from"]
                if isinstance(open_from, date) and close_to <= open_from:
                    close_to = open_from
                conn.execute(
                    text(
                        """
                        UPDATE security_industry
                        SET valid_to = :valid_to
                        WHERE security_id = :security_id
                          AND industry_id = :industry_id
                          AND valid_from = :valid_from
                          AND valid_to IS NULL
                        """
                    ),
                    {
                        "valid_to": close_to,
                        "security_id": security_id,
                        "industry_id": int(open_row["industry_id"]),
                        "valid_from": open_from,
                    },
                )

            insert_from = valid_from
            if open_rows:
                # Reclassification: new interval starts at snapshot (half-open prior).
                insert_from = snapshot_date
            conn.execute(
                text(
                    """
                    INSERT INTO security_industry (
                        security_id, industry_id, valid_from, valid_to, source, ingested_at
                    ) VALUES (
                        :security_id, :industry_id, :valid_from, NULL, :source, :ingested_at
                    )
                    ON CONFLICT (security_id, industry_id, valid_from) DO UPDATE SET
                        valid_to = NULL,
                        source = EXCLUDED.source,
                        ingested_at = EXCLUDED.ingested_at
                    """
                ),
                {
                    "security_id": security_id,
                    "industry_id": industry_id,
                    "valid_from": insert_from,
                    "source": row_source,
                    "ingested_at": now,
                },
            )
            n += 1
        return n
