"""K2 document slicing helpers (re-export)."""

from quantagent.knowledge.ingestion.documents import (
    DocumentChunkDraft,
    chunk_text,
    disclose_at,
    drafts_from_news_row,
    drafts_from_report_pack,
    report_doc_ref,
    report_mda_drafts,
    report_risk_drafts,
    source_to_doc_type,
)
from quantagent.knowledge.ingestion.report_sections import (
    ReportSections,
    extract_report_sections,
    split_mda_subsections,
    split_risk_items,
)

__all__ = [
    "DocumentChunkDraft",
    "ReportSections",
    "chunk_text",
    "disclose_at",
    "drafts_from_news_row",
    "drafts_from_report_pack",
    "extract_report_sections",
    "report_doc_ref",
    "report_mda_drafts",
    "report_risk_drafts",
    "source_to_doc_type",
    "split_mda_subsections",
    "split_risk_items",
]
