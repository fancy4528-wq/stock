"""PIT knowledge tool — wraps ``search_chunks_as_of`` (as_of injected)."""

from __future__ import annotations

from datetime import date
from typing import Any

from quantagent.agents.tools.dispatch import require_as_of
from quantagent.core.repository.pit import PITRepository
from quantagent.knowledge.embedding.base import Embedder
from quantagent.knowledge.retrieval.search import (
    DEFAULT_TOP_K,
    ChunkHit,
    search_chunks_as_of,
)


def search_knowledge(
    query: str,
    *,
    as_of: date | None = None,
    top_k: int = DEFAULT_TOP_K,
    security_id: int | None = None,
    embedder: Embedder | None = None,
    repo: PITRepository | None = None,
) -> list[dict[str, Any]]:
    """Agent-facing RAG tool. ``as_of`` is injected by ``ToolRegistry``.

    Returns truncated chunk dicts (JSON-serializable) for prompt/tool traces.
    """
    day = require_as_of(as_of)
    hits: list[ChunkHit] = search_chunks_as_of(
        query,
        as_of=day,
        top_k=top_k,
        security_id=security_id,
        embedder=embedder,
        repo=repo,
    )
    return [h.model_dump(mode="json") for h in hits]
