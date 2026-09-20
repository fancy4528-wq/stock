"""Embedder protocol and shared constants."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

EMBED_DIM = 1024


@runtime_checkable
class Embedder(Protocol):
    """Produce fixed-dimension dense vectors for RAG."""

    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalizable vector of length ``EMBED_DIM`` per text."""
        ...
