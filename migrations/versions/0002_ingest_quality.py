"""Add ingest_batch and data_quality_check tables.

Revision ID: 0002_ingest_quality
Revises: 0001_p0_schema_pit
Create Date: 2026-09-05

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002_ingest_quality"
down_revision: str | None = "0001_p0_schema_pit"
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
    _execute_sql_file("003_ingest_quality.sql")


def downgrade() -> None:
    _execute_sql_file("901_drop_ingest_quality.sql")
