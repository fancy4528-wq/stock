"""Add news.related_symbol / announce_type for extract hints.

Revision ID: 0006_news_related_symbol
Revises: 0005_news_events
Create Date: 2026-09-13

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0006_news_related_symbol"
down_revision: str | None = "0005_news_events"
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
    _execute_sql_file("007_news_related_symbol.sql")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_news_related_symbol")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS announce_type")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS related_symbol")
