"""K2 document slicing: news / announcements / periodic reports → chunk texts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from quantagent.knowledge.ingestion.report_sections import (
    extract_report_sections,
    split_mda_subsections,
    split_risk_items,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


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


def disclose_at(disclose_date: date | datetime) -> datetime:
    """PIT visibility for reports = disclose calendar day (Asia/Shanghai EOD start).

    Uses midnight Asia/Shanghai on the disclose date — **never** the fiscal period end.
    """
    if isinstance(disclose_date, datetime):
        if disclose_date.tzinfo is None:
            return disclose_date.replace(tzinfo=CN_TZ)
        return disclose_date
    return datetime.combine(disclose_date, time(0, 0), tzinfo=CN_TZ)


def report_doc_ref(
    *,
    symbol: str,
    fiscal_year: int,
    section: str,
    report_kind: str = "annual",
) -> str:
    """Stable ``document_chunk.doc_ref`` for a report section."""
    kind = report_kind.strip().lower() or "annual"
    sec = section.strip().lower()
    if sec not in {"mda", "risk"}:
        raise ValueError(f"unsupported report section: {section!r}")
    return f"report:{symbol}:{fiscal_year}:{kind}:{sec}"


def report_mda_drafts(
    *,
    doc_ref: str,
    content: str,
    visible_at: datetime,
    security_id: int | None = None,
    related_symbol: str | None = None,
    expires_at: datetime | None = None,
    max_chars: int = 800,
) -> list[DocumentChunkDraft]:
    """Slice MD&A text into ``doc_type=report`` drafts (~800 字 / 小节)."""
    pieces = split_mda_subsections(content, max_chars=max_chars)
    return [
        DocumentChunkDraft(
            doc_type="report",
            doc_ref=doc_ref,
            chunk_index=i,
            content=f"[MD&A] {piece}",
            visible_at=visible_at,
            expires_at=expires_at,
            security_id=security_id,
            related_symbol=related_symbol,
        )
        for i, piece in enumerate(pieces)
    ]


def report_risk_drafts(
    *,
    doc_ref: str,
    content: str,
    visible_at: datetime,
    security_id: int | None = None,
    related_symbol: str | None = None,
    expires_at: datetime | None = None,
    max_chars: int = 800,
) -> list[DocumentChunkDraft]:
    """Slice risk-factor text into ``doc_type=report`` drafts (按条目)."""
    pieces = split_risk_items(content, max_chars=max_chars)
    return [
        DocumentChunkDraft(
            doc_type="report",
            doc_ref=doc_ref,
            chunk_index=i,
            content=f"[风险因素] {piece}",
            visible_at=visible_at,
            expires_at=expires_at,
            security_id=security_id,
            related_symbol=related_symbol,
        )
        for i, piece in enumerate(pieces)
    ]


def drafts_from_report_pack(
    pack: dict[str, Any],
    *,
    max_chars: int = 800,
) -> list[DocumentChunkDraft]:
    """Build MD&A + risk drafts from one K2 report pack dict.

    Required keys: ``symbol``, ``fiscal_year``, ``disclose_date``.
    Provide ``mda_text`` / ``risk_text`` and/or ``full_text`` (section markers).
    ``period_end`` is ignored for ``visible_at`` (anti-lookahead).
    """
    symbol = str(pack["symbol"]).strip()
    fiscal_year = int(pack["fiscal_year"])
    report_kind = str(pack.get("report_kind") or "annual").strip().lower()
    raw_disclose = pack["disclose_date"]
    if isinstance(raw_disclose, datetime):
        visible = disclose_at(raw_disclose)
    elif isinstance(raw_disclose, date):
        visible = disclose_at(raw_disclose)
    else:
        visible = disclose_at(date.fromisoformat(str(raw_disclose)[:10]))

    sections = extract_report_sections(
        str(pack.get("full_text") or ""),
        mda_text=str(pack["mda_text"]) if pack.get("mda_text") else None,
        risk_text=str(pack["risk_text"]) if pack.get("risk_text") else None,
    )
    security_id = pack.get("security_id")
    sid = int(security_id) if security_id is not None else None
    drafts: list[DocumentChunkDraft] = []
    if sections.mda:
        drafts.extend(
            report_mda_drafts(
                doc_ref=report_doc_ref(
                    symbol=symbol,
                    fiscal_year=fiscal_year,
                    section="mda",
                    report_kind=report_kind,
                ),
                content=sections.mda,
                visible_at=visible,
                security_id=sid,
                related_symbol=symbol,
                max_chars=max_chars,
            )
        )
    if sections.risk:
        drafts.extend(
            report_risk_drafts(
                doc_ref=report_doc_ref(
                    symbol=symbol,
                    fiscal_year=fiscal_year,
                    section="risk",
                    report_kind=report_kind,
                ),
                content=sections.risk,
                visible_at=visible,
                security_id=sid,
                related_symbol=symbol,
                max_chars=max_chars,
            )
        )
    return drafts
