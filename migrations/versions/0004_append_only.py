"""Append-only shadow_day table and prevent_update_delete trigger.

Revision ID: 0004_append_only
Revises: 0003_prices_as_of_liquidity
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0004_append_only"
down_revision: str | None = "0003_prices_as_of_liquidity"
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
    _execute_sql_file("005_append_only.sql")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS shadow_day_append_only ON shadow_day")
    op.execute("DROP TABLE IF EXISTS shadow_day")
    op.execute("DROP FUNCTION IF EXISTS prevent_update_delete()")
