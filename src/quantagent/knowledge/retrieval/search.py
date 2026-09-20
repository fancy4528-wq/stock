"""PIT-filtered RAG search — sole retrieval entry for agents."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from pydantic import BaseModel, Field

from quantagent.core.repository.pit import PITRepository
from quantagent.knowledge.embedding.base import Embedder
from quantagent.knowledge.embedding.factory import build_embedder

DEFAULT_TOP_K = 5
MAX_CONTENT_CHARS = 2000


class ChunkHit(BaseModel):
    """One retrieved chunk after PIT filtering and truncation."""

    chunk_id: int
    content: str
    doc_type: str
    doc_ref: str
    security_id: int | None = None
    visible_at: datetime
    distance: float
    similarity: float = Field(description="1 - cosine distance")


def search_chunks_as_of(
    query: str,
    *,
    as_of: date,
    top_k: int = DEFAULT_TOP_K,
    security_id: int | None = None,
    embedder: Embedder | None = None,
    repo: PITRepository | None = None,
    max_chars: int = MAX_CONTENT_CHARS,
) -> list[ChunkHit]:
    """Embed ``query`` and search via ``PITRepository.search_chunks`` only.

    ``top_k`` is capped at 5 (Gate 2 / token budget). Content is truncated.
    """
    if not query.strip():
        return []
    k = min(max(int(top_k), 1), DEFAULT_TOP_K)
    emb = embedder or build_embedder()
    pit = repo or PITRepository()
    vectors = emb.embed([query])
    rows = pit.search_chunks(
        vectors[0],
        as_of=as_of,
        limit=k,
        security_id=security_id,
    )
    hits: list[ChunkHit] = []
    for row in rows:
        content = str(row["content"])
        if len(content) > max_chars:
            content = content[: max_chars - 1] + "…"
        dist = float(cast(Any, row["distance"]))
        sec_raw = row.get("security_id")
        sec_id = int(cast(Any, sec_raw)) if sec_raw is not None else None
        hits.append(
            ChunkHit(
                chunk_id=int(cast(Any, row["chunk_id"])),
                content=content,
                doc_type=str(row["doc_type"]),
                doc_ref=str(row["doc_ref"]),
                security_id=sec_id,
                visible_at=_as_datetime(row["visible_at"]),
                distance=dist,
                similarity=1.0 - dist,
            )
        )
    return hits


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    raise TypeError(f"visible_at must be datetime, got {type(value)}")
