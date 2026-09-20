"""Unit tests for PIT-filtered RAG retrieval (mocked repo)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from quantagent.knowledge.embedding.hash_embedder import HashEmbedder
from quantagent.knowledge.retrieval.search import (
    DEFAULT_TOP_K,
    MAX_CONTENT_CHARS,
    search_chunks_as_of,
)


def test_search_caps_top_k_and_truncates() -> None:
    repo = MagicMock()
    long = "字" * (MAX_CONTENT_CHARS + 50)
    repo.search_chunks.return_value = [
        {
            "chunk_id": 1,
            "content": long,
            "doc_type": "announcement",
            "doc_ref": "news:1",
            "security_id": None,
            "visible_at": datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            "distance": 0.1,
        }
    ]
    hits = search_chunks_as_of(
        "合同",
        as_of=date(2026, 9, 10),
        top_k=99,
        embedder=HashEmbedder(),
        repo=repo,
    )
    assert len(hits) == 1
    assert len(hits[0].content) <= MAX_CONTENT_CHARS
    assert hits[0].content.endswith("…")
    assert abs(hits[0].similarity - 0.9) < 1e-9
    kwargs = repo.search_chunks.call_args
    assert kwargs.kwargs["as_of"] == date(2026, 9, 10)
    assert kwargs.kwargs["limit"] == DEFAULT_TOP_K


def test_search_empty_query() -> None:
    repo = MagicMock()
    assert search_chunks_as_of("  ", as_of=date(2026, 1, 1), repo=repo) == []
    repo.search_chunks.assert_not_called()


def test_search_requires_keyword_as_of() -> None:
    with pytest.raises(TypeError):
        search_chunks_as_of("q", date(2026, 1, 1))  # type: ignore[misc]


def test_sentinel_future_chunk_filtered_by_repo_contract() -> None:
    """Knowledge layer trusts PITRepository; future rows must not be returned.

    Simulate repo correctly omitting a future-visible chunk.
    """
    repo = MagicMock()
    # Only the past-visible chunk is returned (as SQL function would).
    repo.search_chunks.return_value = [
        {
            "chunk_id": 10,
            "content": "历史公告",
            "doc_type": "announcement",
            "doc_ref": "news:10",
            "security_id": 1,
            "visible_at": datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
            "distance": 0.2,
        }
    ]
    hits = search_chunks_as_of(
        "公告",
        as_of=date(2026, 6, 1),
        embedder=HashEmbedder(),
        repo=repo,
    )
    assert [h.chunk_id for h in hits] == [10]
    assert all(h.visible_at.date() <= date(2026, 6, 1) for h in hits)
