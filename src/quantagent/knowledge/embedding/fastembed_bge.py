"""Optional local embedding via fastembed (1024-d, Chinese-capable)."""

from __future__ import annotations

from typing import Any

from quantagent.knowledge.embedding.base import EMBED_DIM
from quantagent.shared.errors import DataError

# fastembed does NOT ship BAAI/bge-large-zh-v1.5 (only bge-small-zh @ 512-d).
# multilingual-e5-large is 1024-d and supports Chinese — matches document_chunk.
DEFAULT_FASTEMBED_MODEL = "intfloat/multilingual-e5-large"


class FastEmbedBge:
    """Local embedding via ``fastembed`` (zero API cost)."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_FASTEMBED_MODEL,
        dim: int = EMBED_DIM,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - optional extra
            raise DataError(
                "fastembed is not installed; run: uv sync --extra embedding "
                "or set EMBEDDING_BACKEND=hash"
            ) from exc
        self.model_name = model_name
        self._dim = dim
        try:
            self._model: Any = TextEmbedding(model_name=model_name)
        except ValueError as exc:
            hints: list[str] = []
            for item in TextEmbedding.list_supported_models():
                n = str(item.get("model") or item.get("model_name") or "")
                d = item.get("dim") or item.get("dimensions")
                if not n:
                    continue
                if d == dim or "zh" in n.lower() or "multilingual" in n.lower():
                    hints.append(n)
            hint = ", ".join(hints[:8]) or "(see TextEmbedding.list_supported_models())"
            raise DataError(
                f"fastembed does not support model {model_name!r} "
                f"(need dim={dim}). Try EMBEDDING_MODEL={DEFAULT_FASTEMBED_MODEL!r} "
                f"or one of: {hint}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — surface download/network clearly
            raise DataError(
                f"Failed to load embedding model {model_name!r}: {exc}. "
                "First run downloads weights from HuggingFace. "
                "If timed out in CN, set HF_ENDPOINT=https://hf-mirror.com "
                "then retry; or use EMBEDDING_BACKEND=hash for offline."
            ) from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # e5 models expect "query: "/"passage: " prefixes for best quality;
        # for chunk+query symmetry we use passage-style for both (retrieval OK).
        prefixed = [t if t.startswith(("query:", "passage:")) else f"passage: {t}" for t in texts]
        out: list[list[float]] = []
        for vec in self._model.embed(prefixed):
            row = [float(x) for x in vec]
            if len(row) != self._dim:
                raise DataError(
                    f"Embedding dim mismatch: got {len(row)}, expected {self._dim} "
                    f"(model={self.model_name})"
                )
            out.append(row)
        return out
