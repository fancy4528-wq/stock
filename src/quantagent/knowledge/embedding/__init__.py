"""Embedding backends for RAG (local / test)."""

from quantagent.knowledge.embedding.base import EMBED_DIM, Embedder
from quantagent.knowledge.embedding.factory import build_embedder
from quantagent.knowledge.embedding.hash_embedder import HashEmbedder

__all__ = ["EMBED_DIM", "Embedder", "HashEmbedder", "build_embedder"]
