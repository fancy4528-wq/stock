"""P0 schema and PIT SQL functions.

Revision ID: 0001_p0_schema_pit
Revises:
Create Date: 2026-09-05

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_p0_schema_pit"
down_revision: str | None = None
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
    _execute_sql_file("001_p0_schema.sql")
    _execute_sql_file("002_pit_functions.sql")


def downgrade() -> None:
    _execute_sql_file("900_drop_p0.sql")
