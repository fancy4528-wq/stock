"""Knowledge layer: K2 document RAG (P2)."""

from quantagent.knowledge.embedding.factory import build_embedder
from quantagent.knowledge.retrieval.search import ChunkHit, search_chunks_as_of

__all__ = ["ChunkHit", "build_embedder", "search_chunks_as_of"]
