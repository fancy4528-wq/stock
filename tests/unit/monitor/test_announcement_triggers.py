"""Unit tests: C-class announcement triggers."""

from __future__ import annotations

from quantagent.monitor.triggers.announcement import (
    AnnouncementItem,
    AnnouncementTypeConfig,
    evaluate_announcement_triggers,
    match_announcement_severity,
)


def test_match_critical_and_high() -> None:
    cfg = AnnouncementTypeConfig(
        critical=["立案调查", "预亏"],
        high=["股东减持", "回购"],
    )
    assert (
        match_announcement_severity(announce_type="立案调查", title="收到通知", cfg=cfg)
        == "critical"
    )
    assert (
        match_announcement_severity(announce_type=None, title="公司预亏约2亿元", cfg=cfg)
        == "critical"
    )
    assert (
        match_announcement_severity(announce_type="持股变动", title="控股股东股东减持计划", cfg=cfg)
        == "high"
    )
    assert match_announcement_severity(announce_type="日常经营", title="普通公告", cfg=cfg) is None


def test_evaluate_only_holdings() -> None:
    cfg = AnnouncementTypeConfig(critical=["立案调查"], high=["回购"])
    items = [
        AnnouncementItem(
            symbol="600519.SH",
            title="立案调查告知书",
            announce_type="立案调查",
            news_id=1,
            source="em_announce",
            name="茅台",
        ),
        AnnouncementItem(
            symbol="000001.SZ",
            title="回购进展",
            announce_type="回购",
            news_id=2,
            source="em_announce",
        ),
    ]
    hits = evaluate_announcement_triggers(
        items, {"600519.SH"}, name_by_symbol={"600519.SH": "茅台"}, cfg=cfg
    )
    assert len(hits) == 1
    assert hits[0].severity == "critical"
    assert hits[0].symbol == "600519.SH"
    assert "ANN_CRITICAL" in hits[0].code
    assert hits[0].cost_usd == 0.0
