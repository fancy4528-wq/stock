"""Unit tests for K2 MD&A / risk section extraction and report packs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quantagent.data.collectors.reports.pack import (
    default_fixture_pack_path,
    load_report_packs,
)
from quantagent.knowledge.ingestion.documents import (
    disclose_at,
    drafts_from_report_pack,
    report_doc_ref,
    report_mda_drafts,
    report_risk_drafts,
)
from quantagent.knowledge.ingestion.report_sections import (
    extract_report_sections,
    extract_section,
    split_mda_subsections,
    split_risk_items,
)
from quantagent.shared.errors import DataError

CN_TZ = ZoneInfo("Asia/Shanghai")

_SAMPLE = """
第一节 释义
略。

第三节 管理层讨论与分析
一、行业情况
白酒需求平稳。
二、主营业务
公司实现营业收入增长，毛利率稳定。
三、核心竞争力
品牌与产能构成护城河。

第四节 公司治理
略。

第六节 可能面对的风险
（一）宏观风险
消费景气下降可能影响销量。
（二）政策风险
监管趋严增加合规成本。
（三）原材料风险
粮食价格波动。

第七节 财务报告
略。
"""


def test_extract_mda_and_risk_from_full_text() -> None:
    sections = extract_report_sections(_SAMPLE)
    assert "白酒需求平稳" in sections.mda
    assert "公司治理" not in sections.mda
    assert "宏观风险" in sections.risk
    assert "财务报告" not in sections.risk


def test_explicit_fields_override_full_text() -> None:
    sections = extract_report_sections(
        _SAMPLE,
        mda_text="显式MD&A",
        risk_text="显式风险",
    )
    assert sections.mda == "显式MD&A"
    assert sections.risk == "显式风险"


def test_split_mda_and_risk() -> None:
    sections = extract_report_sections(_SAMPLE)
    mda_parts = split_mda_subsections(sections.mda, max_chars=800)
    risk_parts = split_risk_items(sections.risk, max_chars=800)
    assert len(mda_parts) >= 2
    assert len(risk_parts) >= 2
    assert any("主营业务" in p for p in mda_parts)
    assert any("政策风险" in p for p in risk_parts)


def test_disclose_at_uses_calendar_day_not_period_end() -> None:
    visible = disclose_at(date(2025, 3, 28))
    assert visible == datetime(2025, 3, 28, 0, 0, tzinfo=CN_TZ)
    # period_end must never be treated as visible_at by callers
    assert visible.date() != date(2024, 12, 31)


def test_drafts_from_report_pack_visible_at_is_disclose() -> None:
    pack = {
        "symbol": "600519.SH",
        "fiscal_year": 2024,
        "report_kind": "annual",
        "disclose_date": "2025-03-28",
        "period_end": "2024-12-31",
        "full_text": _SAMPLE,
    }
    drafts = drafts_from_report_pack(pack)
    assert drafts
    assert all(d.doc_type == "report" for d in drafts)
    assert all(d.visible_at.date() == date(2025, 3, 28) for d in drafts)
    assert all(d.visible_at.date() != date(2024, 12, 31) for d in drafts)
    mda = [d for d in drafts if d.doc_ref.endswith(":mda")]
    risk = [d for d in drafts if d.doc_ref.endswith(":risk")]
    assert mda and risk
    assert mda[0].content.startswith("[MD&A]")
    assert risk[0].content.startswith("[风险因素]")
    assert mda[0].related_symbol == "600519.SH"


def test_report_doc_ref() -> None:
    assert (
        report_doc_ref(symbol="600519.SH", fiscal_year=2024, section="mda")
        == "report:600519.SH:2024:annual:mda"
    )
    with pytest.raises(ValueError):
        report_doc_ref(symbol="x", fiscal_year=2024, section="other")


def test_report_mda_and_risk_drafts() -> None:
    visible = datetime(2025, 4, 15, 0, 0, tzinfo=UTC)
    mda = report_mda_drafts(
        doc_ref="report:x:2024:annual:mda",
        content="一、概述\n经营稳健。\n二、展望\n继续扩产。" + ("详" * 200),
        visible_at=visible,
        security_id=7,
    )
    risk = report_risk_drafts(
        doc_ref="report:x:2024:annual:risk",
        content="1、市场风险：竞争加剧。\n2、政策风险：监管变化。",
        visible_at=visible,
    )
    assert mda and risk
    assert mda[0].doc_type == "report"
    assert risk[0].chunk_index == 0


def test_fixture_pack_loads_and_slices() -> None:
    path = default_fixture_pack_path()
    assert path.exists(), path
    packs = load_report_packs(path)
    assert len(packs) >= 3
    drafts = []
    for pack in packs:
        drafts.extend(drafts_from_report_pack(pack))
    assert any(d.doc_ref.endswith(":mda") for d in drafts)
    assert any(d.doc_ref.endswith(":risk") for d in drafts)
    # 半年报 kind 进入 doc_ref
    assert any(":semi:mda" in d.doc_ref for d in drafts)


def test_load_report_packs_rejects_missing_body(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"symbol":"600000.SH","fiscal_year":2024,"disclose_date":"2025-01-01"}\n',
        encoding="utf-8",
    )
    with pytest.raises(DataError, match="mda_text"):
        load_report_packs(bad)


def test_extract_section_empty_without_marker() -> None:
    from quantagent.knowledge.ingestion.report_sections import _MDA_START

    assert extract_section("没有任何标题", start=_MDA_START) == ""
