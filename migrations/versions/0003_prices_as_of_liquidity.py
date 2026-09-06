"""Extend get_prices_as_of with amount / turnover_rate / prev_close.

Revision ID: 0003_prices_as_of_liquidity
Revises: 0002_ingest_quality
Create Date: 2026-09-06

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0003_prices_as_of_liquidity"
down_revision: str | None = "0002_ingest_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "quantagent"
    / "core"
    / "repository"
    / "sql"
)


def _execute_sql_file(name: str) -> None:
    sql = (_SQL_DIR / name).read_text(encoding="utf-8")
    op.execute(sql)


def upgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS get_prices_as_of(bigint[], date, date, timestamptz, text)"
    )
    _execute_sql_file("004_prices_as_of_liquidity.sql")


def downgrade() -> None:
    # Restore prior signature (without liquidity columns) from 002 snapshot.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION get_prices_as_of(
            p_security_ids BIGINT[],
            p_start        DATE,
            p_end          DATE,
            p_as_of        TIMESTAMPTZ,
            p_adjust       TEXT DEFAULT 'qfq'
        ) RETURNS TABLE (
            security_id BIGINT,
            trade_date DATE,
            open NUMERIC,
            high NUMERIC,
            low NUMERIC,
            close NUMERIC,
            volume BIGINT,
            is_limit_up BOOLEAN,
            is_limit_down BOOLEAN,
            is_suspended BOOLEAN
        ) AS $$
            WITH af AS (
                SELECT DISTINCT ON (security_id, trade_date)
                       security_id,
                       trade_date,
                       factor_qfq,
                       factor_hfq
                FROM adjust_factor
                WHERE security_id = ANY(p_security_ids)
                  AND announced_at <= p_as_of
                ORDER BY security_id, trade_date, revision DESC
            )
            SELECT
                p.security_id,
                p.trade_date,
                p.open  * COALESCE(
                    CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
                ),
                p.high  * COALESCE(
                    CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
                ),
                p.low   * COALESCE(
                    CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
                ),
                p.close * COALESCE(
                    CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
                ),
                p.volume,
                p.is_limit_up,
                p.is_limit_down,
                p.is_suspended
            FROM price_daily p
            LEFT JOIN af f USING (security_id, trade_date)
            WHERE p.security_id = ANY(p_security_ids)
              AND p.trade_date BETWEEN p_start AND p_end
              AND p.trade_date <= p_as_of::date
            ORDER BY p.security_id, p.trade_date;
        $$ LANGUAGE sql STABLE;
        """
    )
