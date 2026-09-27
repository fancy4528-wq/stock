"""Unit tests: L1 keyword severity table."""

from __future__ import annotations

from quantagent.monitor.funnel.keywords import KeywordConfig, keyword_severity, load_keyword_config


def test_severity_tiers() -> None:
    cfg = KeywordConfig(
        critical=["立案调查", "业绩预亏"],
        high=["重大合同", "解禁"],
        medium=["机构调研", "分红"],
    )
    assert keyword_severity("公司收到立案调查通知书", cfg=cfg) == "critical"
    assert keyword_severity("签署重大合同公告", cfg=cfg) == "high"
    assert keyword_severity("接待机构调研", cfg=cfg) == "medium"
    assert keyword_severity("日常经营正常", cfg=cfg) == "none"


def test_critical_beats_overlapping_high() -> None:
    cfg = KeywordConfig(
        critical=["业绩预告-预亏"],
        high=["业绩预告"],
        medium=[],
    )
    assert keyword_severity("披露业绩预告-预亏", cfg=cfg) == "critical"


def test_load_default_keywords_nonempty() -> None:
    cfg = load_keyword_config()
    assert "立案调查" in cfg.critical
    assert "重大合同" in cfg.high
    assert "机构调研" in cfg.medium
