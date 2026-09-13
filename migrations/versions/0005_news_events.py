"""News + event / event_security tables for P2.

Revision ID: 0005_news_events
Revises: 0004_append_only
Create Date: 2026-09-13

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0005_news_events"
down_revision: str | None = "0004_append_only"
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
    _execute_sql_file("006_news_events.sql")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS event_security CASCADE")
    op.execute("DROP TABLE IF EXISTS event CASCADE")
    op.execute("DROP TABLE IF EXISTS news CASCADE")
