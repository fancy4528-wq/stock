"""Unit tests for rule_v1 NewsExtractor + figure gold baseline."""

from __future__ import annotations

from pathlib import Path

from quantagent.agents.news_extractor import RuleNewsExtractor, extract_figures
from quantagent.agents.news_extractor.eval import score_figures_gold

GOLD = Path(__file__).resolve().parents[2] / "fixtures" / "extraction" / "figures_gold.jsonl"


def test_extract_figures_basic() -> None:
    figs = extract_figures("公司实现营收12.3亿元，同比增长15%")
    labels = {f.label for f in figs}
    assert "营收" in labels
    assert any(f.label == "同比" and f.value == 15.0 for f in figs)


def test_extract_figures_negative_yoy() -> None:
    figs = extract_figures("同比下降12%")
    assert any(f.label == "同比" and f.value == -12.0 and f.unit == "%" for f in figs)


def test_rule_extractor_contract_and_symbol() -> None:
    ext = RuleNewsExtractor()
    out = ext.extract(
        title="600519.SH 中标金额1.2亿元重大合同",
        body="贵州茅台中标，金额1.2亿元。",
        announce_type="重大合同",
    )
    assert out.is_relevant
    assert out.event_type == "contract"
    assert "600519.SH" in out.primary_symbols
    assert out.figures
    assert out.direction in {"positive", "neutral", "unclear"}


def test_figures_gold_soft_rate() -> None:
    score = score_figures_gold(GOLD)
    assert score.n >= 25
    assert score.soft_rate >= 0.8
