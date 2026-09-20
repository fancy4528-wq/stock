"""Deterministic hash embedder for CI / default (zero model download)."""

from __future__ import annotations

import hashlib
import math
import struct

from quantagent.knowledge.embedding.base import EMBED_DIM


class HashEmbedder:
    """Map text → 1024-d pseudo-vector via SHA-256 expansions.

    Not semantically meaningful; keeps unit tests and offline ingest working
    without ``fastembed`` / model weights. Same input → same vector.
    """

    model_name = "hash_v1"

    def __init__(self, *, dim: int = EMBED_DIM) -> None:
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        seed = text.encode()
        values: list[float] = []
        counter = 0
        while len(values) < self._dim:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for i in range(0, len(digest), 4):
                if len(values) >= self._dim:
                    break
                (u,) = struct.unpack_from(">I", digest, i)
                # Map to (-1, 1)
                values.append((u / 0xFFFFFFFF) * 2.0 - 1.0)
            counter += 1
        return _l2_normalize(values)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return vec
    return [x / norm for x in vec]
