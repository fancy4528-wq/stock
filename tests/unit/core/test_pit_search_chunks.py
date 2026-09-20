"""Unit tests for PITRepository.search_chunks (mocked engine)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from quantagent.core.repository.pit import PITRepository
from quantagent.knowledge.embedding.hash_embedder import HashEmbedder
from quantagent.shared.errors import LookaheadError

CN_TZ = ZoneInfo("Asia/Shanghai")


def _repo() -> PITRepository:
    repo = PITRepository.__new__(PITRepository)
    repo._engine = MagicMock()
    return repo


def _connect_ctx(conn: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


def test_search_chunks_passes_eod_as_of() -> None:
    repo = _repo()
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "chunk_id": 1,
            "content": "ok",
            "doc_type": "news",
            "doc_ref": "news:1",
            "security_id": None,
            "visible_at": datetime(2026, 9, 1, 10, 0, tzinfo=CN_TZ),
            "distance": 0.05,
        }
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    vec = HashEmbedder().embed(["q"])[0]
    rows = repo.search_chunks(vec, as_of=date(2026, 9, 10), limit=3)
    assert len(rows) == 1
    params = conn.execute.call_args.args[1]
    assert params["as_of"] == datetime(2026, 9, 10, 15, 0, tzinfo=CN_TZ)
    assert params["limit"] == 3


def test_search_chunks_lookahead_guard() -> None:
    repo = _repo()
    conn = MagicMock()
    # Simulate a bug that returns a future-visible chunk.
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "chunk_id": 99,
            "content": "未来文档",
            "doc_type": "announcement",
            "doc_ref": "news:99",
            "security_id": None,
            "visible_at": datetime(2026, 12, 31, 10, 0, tzinfo=CN_TZ),
            "distance": 0.01,
        }
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    vec = HashEmbedder().embed(["q"])[0]
    with pytest.raises(LookaheadError, match="future visible_at"):
        repo.search_chunks(vec, as_of=date(2026, 6, 1), limit=5)


def test_search_chunks_empty_limit() -> None:
    repo = _repo()
    assert repo.search_chunks([0.1] * 8, as_of=date(2026, 1, 1), limit=0) == []


def test_search_chunks_requires_as_of_keyword() -> None:
    repo = _repo()
    with pytest.raises(TypeError):
        repo.search_chunks([0.1], date(2026, 1, 1))  # type: ignore[misc]
