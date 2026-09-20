"""Factory: hash (default) or fastembed when configured."""

from __future__ import annotations

from quantagent.knowledge.embedding.base import Embedder
from quantagent.knowledge.embedding.hash_embedder import HashEmbedder
from quantagent.shared.config.settings import get_settings


def build_embedder(
    *,
    backend: str | None = None,
    model_name: str | None = None,
) -> Embedder:
    """Return an ``Embedder``.

    ``EMBEDDING_BACKEND=hash`` (default) → deterministic HashEmbedder.
    ``EMBEDDING_BACKEND=fastembed`` → local model via optional ``fastembed`` extra
    (default ``intfloat/multilingual-e5-large``, override with ``EMBEDDING_MODEL``).
    """
    settings = get_settings()
    name = (backend if backend is not None else settings.embedding_backend).strip().lower()
    if name in ("", "hash", "hash_v1"):
        return HashEmbedder()
    if name in ("fastembed", "bge", "local"):
        from quantagent.knowledge.embedding.fastembed_bge import (
            DEFAULT_FASTEMBED_MODEL,
            FastEmbedBge,
        )

        model = (model_name if model_name is not None else settings.embedding_model) or ""
        model = model.strip() or DEFAULT_FASTEMBED_MODEL
        return FastEmbedBge(model_name=model)
    raise ValueError(f"Unknown EMBEDDING_BACKEND: {name!r} (use hash|fastembed)")
