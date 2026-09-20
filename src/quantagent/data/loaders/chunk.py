"""Persist document chunks + embeddings into ``document_chunk``."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.engine import Engine

from quantagent.data.collectors.reports.pack import (
    default_fixture_pack_path,
    load_report_packs,
)
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.knowledge.embedding.base import Embedder
from quantagent.knowledge.embedding.factory import build_embedder
from quantagent.knowledge.ingestion.documents import (
    DocumentChunkDraft,
    drafts_from_news_row,
    drafts_from_report_pack,
)
from quantagent.shared.config import get_settings

CN_TZ = ZoneInfo("Asia/Shanghai")


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


class ChunkLoader:
    """Upsert slices into ``document_chunk`` (idempotent on doc_ref + chunk_index)."""

    def __init__(
        self,
        engine: Engine | None = None,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        if engine is not None:
            self._engine = engine
        else:
            self._engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        self._embedder: Embedder = embedder or build_embedder()

    def load_drafts(self, drafts: list[DocumentChunkDraft]) -> dict[str, int]:
        if not drafts:
            return {"chunks": 0, "skipped": 0}
        vectors = self._embedder.embed([d.content for d in drafts])
        model = self._embedder.model_name
        upserted = 0
        with self._engine.begin() as conn:
            for draft, vec in zip(drafts, vectors, strict=True):
                sid = draft.security_id
                if sid is None and draft.related_symbol:
                    sid = self._resolve_security_id(conn, draft.related_symbol)
                self._upsert(
                    conn,
                    draft=draft,
                    security_id=sid,
                    embedding=vec,
                    embed_model=model,
                )
                upserted += 1
        return {"chunks": upserted, "skipped": 0}

    def ingest_news(
        self,
        *,
        limit: int = 500,
        since: date | None = None,
        sources: list[str] | None = None,
    ) -> dict[str, int]:
        """Fetch recent ``news`` rows, slice, embed, upsert."""
        rows = self.fetch_news_for_chunking(limit=limit, since=since, sources=sources)
        drafts: list[DocumentChunkDraft] = []
        for row in rows:
            drafts.extend(drafts_from_news_row(row))
        stats = self.load_drafts(drafts)
        return {"news_rows": len(rows), **stats}

    def ingest_reports(
        self,
        *,
        pack_path: Path | None = None,
        load: bool = True,
    ) -> dict[str, int]:
        """Slice K2 report packs (MD&A + risk) → embed → ``document_chunk``."""
        path = pack_path or default_fixture_pack_path()
        packs = load_report_packs(path)
        drafts: list[DocumentChunkDraft] = []
        for pack in packs:
            drafts.extend(drafts_from_report_pack(pack))
        stats = {"packs": len(packs), "drafts": len(drafts), "chunks": 0, "skipped": 0}
        if load and drafts:
            loaded = self.load_drafts(drafts)
            stats["chunks"] = loaded["chunks"]
            stats["skipped"] = loaded["skipped"]
        return stats

    def fetch_news_for_chunking(
        self,
        *,
        limit: int = 500,
        since: date | None = None,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        src = sources or ["em_announce", "cls", "em"]
        since_dt: datetime | None = None
        if since is not None:
            since_dt = datetime.combine(since, datetime.min.time(), tzinfo=CN_TZ)
        else:
            since_dt = datetime.now(CN_TZ) - timedelta(days=30)

        stmt = text(
            """
            SELECT news_id, source, title, body, published_at, related_symbol
            FROM news
            WHERE source = ANY(:sources)
              AND published_at >= :since
            ORDER BY published_at DESC, news_id DESC
            LIMIT :limit
            """
        ).bindparams(bindparam("sources", type_=ARRAY(TEXT())))
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {"sources": src, "since": since_dt, "limit": limit},
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    def _resolve_security_id(self, conn: Connection, symbol: str) -> int | None:
        try:
            canon = normalize_symbol(symbol, market="CN")
        except ValueError:
            return None
        row = conn.execute(
            text("SELECT security_id FROM security WHERE symbol = :symbol"),
            {"symbol": canon},
        ).scalar_one_or_none()
        return int(row) if row is not None else None

    def _upsert(
        self,
        conn: Connection,
        *,
        draft: DocumentChunkDraft,
        security_id: int | None,
        embedding: list[float],
        embed_model: str,
    ) -> None:
        stmt = text(
            """
            INSERT INTO document_chunk (
                doc_type, doc_ref, security_id, chunk_index, content,
                visible_at, expires_at, embedding, embed_model
            ) VALUES (
                :doc_type, :doc_ref, :security_id, :chunk_index, :content,
                :visible_at, :expires_at, CAST(:embedding AS vector), :embed_model
            )
            ON CONFLICT (doc_ref, chunk_index) DO UPDATE SET
                doc_type = EXCLUDED.doc_type,
                security_id = COALESCE(EXCLUDED.security_id, document_chunk.security_id),
                content = EXCLUDED.content,
                visible_at = EXCLUDED.visible_at,
                expires_at = EXCLUDED.expires_at,
                embedding = EXCLUDED.embedding,
                embed_model = EXCLUDED.embed_model
            """
        )
        conn.execute(
            stmt,
            {
                "doc_type": draft.doc_type,
                "doc_ref": draft.doc_ref,
                "security_id": security_id,
                "chunk_index": draft.chunk_index,
                "content": draft.content,
                "visible_at": draft.visible_at,
                "expires_at": draft.expires_at,
                "embedding": _vector_literal(embedding),
                "embed_model": embed_model,
            },
        )
