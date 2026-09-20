"""K2 document slicing: news / announcements → chunk texts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DocumentChunkDraft:
    """One slice ready for embedding + load (no vector yet)."""

    doc_type: str
    doc_ref: str
    chunk_index: int
    content: str
    visible_at: datetime
    expires_at: datetime | None = None
    security_id: int | None = None
    related_symbol: str | None = None


def source_to_doc_type(source: str) -> str:
    """Map ``news.source`` to ``document_chunk.doc_type``."""
    if source == "em_announce":
        return "announcement"
    if source in ("cls", "em"):
        return "news"
    return "news"


def chunk_text(
    text: str,
    *,
    max_chars: int = 800,
    overlap: int = 80,
) -> list[str]:
    """Split Chinese/long text into overlapping character windows."""
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be in [0, max_chars)")
    if len(cleaned) <= max_chars:
        return [cleaned]
    step = max_chars - overlap
    out: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        out.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start += step
    return out


def drafts_from_news_row(
    row: dict[str, Any],
    *,
    max_chars: int = 800,
    overlap: int = 80,
) -> list[DocumentChunkDraft]:
    """Build chunk drafts from one ``news`` table row dict."""
    news_id = int(row["news_id"])
    source = str(row.get("source") or "")
    title = str(row.get("title") or "").strip()
    body = (row.get("body") or "") or ""
    body_s = str(body).strip()
    combined = title if not body_s else f"{title}\n{body_s}"
    pieces = chunk_text(combined, max_chars=max_chars, overlap=overlap)
    if not pieces:
        return []
    visible_at = row["published_at"]
    if not isinstance(visible_at, datetime):
        raise TypeError(f"published_at must be datetime, got {type(visible_at)}")
    related = row.get("related_symbol")
    related_s = str(related).strip() if related else None
    doc_type = source_to_doc_type(source)
    doc_ref = f"news:{news_id}"
    return [
        DocumentChunkDraft(
            doc_type=doc_type,
            doc_ref=doc_ref,
            chunk_index=i,
            content=piece,
            visible_at=visible_at,
            related_symbol=related_s or None,
        )
        for i, piece in enumerate(pieces)
    ]


def report_mda_drafts(
    *,
    doc_ref: str,
    content: str,
    visible_at: datetime,
    security_id: int | None = None,
    expires_at: datetime | None = None,
    max_chars: int = 800,
    overlap: int = 80,
) -> list[DocumentChunkDraft]:
    """Placeholder path for annual-report MD&A (collector comes later)."""
    pieces = chunk_text(content, max_chars=max_chars, overlap=overlap)
    return [
        DocumentChunkDraft(
            doc_type="report",
            doc_ref=doc_ref,
            chunk_index=i,
            content=piece,
            visible_at=visible_at,
            expires_at=expires_at,
            security_id=security_id,
        )
        for i, piece in enumerate(pieces)
    ]
