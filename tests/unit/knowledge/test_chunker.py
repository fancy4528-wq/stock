"""Unit tests for document chunking."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quantagent.knowledge.ingestion.documents import (
    chunk_text,
    drafts_from_news_row,
    report_mda_drafts,
    source_to_doc_type,
)


def test_source_to_doc_type() -> None:
    assert source_to_doc_type("em_announce") == "announcement"
    assert source_to_doc_type("cls") == "news"
    assert source_to_doc_type("em") == "news"


def test_chunk_text_overlap() -> None:
    text = "甲" * 50 + "乙" * 50 + "丙" * 50
    parts = chunk_text(text, max_chars=100, overlap=20)
    assert len(parts) >= 2
    assert all(len(p) <= 100 for p in parts)
    # overlap means consecutive windows share prefix/suffix region
    assert parts[0][-20:] == parts[1][:20]


def test_chunk_text_short() -> None:
    assert chunk_text("短文本", max_chars=800) == ["短文本"]
    assert chunk_text("   ") == []


def test_chunk_text_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=10, overlap=10)


def test_drafts_from_news_row() -> None:
    row = {
        "news_id": 42,
        "source": "em_announce",
        "title": "关于重大合同的公告",
        "body": "公司签署合同金额1亿元。" + ("详" * 900),
        "published_at": datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        "related_symbol": "600519.SH",
    }
    drafts = drafts_from_news_row(row, max_chars=800, overlap=80)
    assert len(drafts) >= 2
    assert drafts[0].doc_type == "announcement"
    assert drafts[0].doc_ref == "news:42"
    assert drafts[0].related_symbol == "600519.SH"
    assert drafts[0].chunk_index == 0
    assert drafts[1].chunk_index == 1


def test_report_mda_drafts_placeholder() -> None:
    visible = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    drafts = report_mda_drafts(
        doc_ref="report:600519:2025",
        content="管理层讨论与分析：" + ("经营" * 400),
        visible_at=visible,
        security_id=7,
    )
    assert drafts
    assert drafts[0].doc_type == "report"
    assert drafts[0].doc_ref == "report:600519:2025"
    assert drafts[0].security_id == 7
    assert drafts[0].visible_at == visible
