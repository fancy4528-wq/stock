"""Unit tests for HashEmbedder and embedder factory."""

from __future__ import annotations

import pytest

from quantagent.knowledge.embedding.base import EMBED_DIM
from quantagent.knowledge.embedding.factory import build_embedder
from quantagent.knowledge.embedding.hash_embedder import HashEmbedder
from quantagent.shared.config.settings import get_settings


def test_hash_embedder_dim_and_deterministic() -> None:
    emb = HashEmbedder()
    a = emb.embed(["贵州茅台业绩预告"])
    b = emb.embed(["贵州茅台业绩预告"])
    c = emb.embed(["不同文本"])
    assert len(a) == 1 and len(a[0]) == EMBED_DIM
    assert a[0] == b[0]
    assert a[0] != c[0]
    # roughly unit length
    norm = sum(x * x for x in a[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_build_embedder_default_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    get_settings.cache_clear()
    try:
        emb = build_embedder()
        assert isinstance(emb, HashEmbedder)
        assert emb.model_name == "hash_v1"
    finally:
        get_settings.cache_clear()


def test_build_embedder_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown EMBEDDING_BACKEND"):
        build_embedder(backend="openai")
