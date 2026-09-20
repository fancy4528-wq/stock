"""Add document_chunk + search_chunks_as_of (P2 RAG).

Revision ID: 0007_document_chunk
Revises: 0006_news_related_symbol
Create Date: 2026-09-20

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0007_document_chunk"
down_revision: str | None = "0006_news_related_symbol"
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
    _execute_sql_file("008_document_chunk.sql")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS search_chunks_as_of(vector, timestamptz, int, bigint)")
    op.execute("DROP INDEX IF EXISTS idx_chunk_doc_ref")
    op.execute("DROP INDEX IF EXISTS idx_chunk_security")
    op.execute("DROP INDEX IF EXISTS idx_chunk_visible")
    op.execute("DROP INDEX IF EXISTS idx_chunk_embedding")
    op.execute("DROP TABLE IF EXISTS document_chunk CASCADE")
