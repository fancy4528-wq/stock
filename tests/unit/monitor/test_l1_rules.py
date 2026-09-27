"""Unit tests: L1 news filter (entity + keyword)."""

from __future__ import annotations

import ast
from pathlib import Path

from quantagent.monitor.funnel.entity_matcher import EntityAliasConfig
from quantagent.monitor.funnel.keywords import KeywordConfig
from quantagent.monitor.funnel.l1_rules import L1Filter, L1News


def _filter() -> L1Filter:
    return L1Filter(
        entity_cfg=EntityAliasConfig(
            aliases={
                "600519.SH": ["贵州茅台", "茅台"],
                "000858.SZ": ["五粮液"],
            },
            industries={"食品饮料": ["白酒", "食品饮料"]},
        ),
        keyword_cfg=KeywordConfig(
            critical=["立案调查", "业绩预亏"],
            high=["重大合同", "解禁"],
            medium=["机构调研"],
        ),
    )


def test_pass_entity_and_high_keyword() -> None:
    f = _filter()
    result = f.check_news(
        L1News(title="茅台签署重大合同"),
        {"600519.SH", "000858.SZ"},
    )
    assert result.passed is True
    assert result.mentioned_symbols == ["600519.SH"]
    assert result.severity == "high"
    assert result.match_kind == "entity"


def test_drop_no_holding_relevance() -> None:
    f = _filter()
    result = f.check_news(
        L1News(title="某科技公司立案调查"),
        {"600519.SH"},
    )
    assert result.passed is False
    assert result.reason == "no_holding_relevance"


def test_drop_low_severity_keywords() -> None:
    f = _filter()
    result = f.check_news(
        L1News(title="茅台举办品牌文化活动"),
        {"600519.SH"},
    )
    assert result.passed is False
    assert result.reason == "low_severity_keywords"


def test_pass_via_industry_match_on_summary() -> None:
    f = _filter()
    result = f.check_news(
        L1News(title="板块异动与解禁压力", summary="今日白酒整体承压"),
        {"600519.SH", "000858.SZ"},
        industry_by_symbol={
            "600519.SH": "食品饮料",
            "000858.SZ": "食品饮料",
        },
    )
    assert result.passed is True
    assert result.match_kind == "industry"
    assert set(result.mentioned_symbols) == {"600519.SH", "000858.SZ"}
    assert result.severity == "high"


def test_l1_rules_have_no_agents_imports() -> None:
    """Architecture: monitor.funnel.l1_rules must not import agents."""
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "src" / "quantagent" / "monitor" / "funnel" / "l1_rules.py",
        root / "src" / "quantagent" / "monitor" / "funnel" / "entity_matcher.py",
        root / "src" / "quantagent" / "monitor" / "funnel" / "keywords.py",
        root / "src" / "quantagent" / "monitor" / "funnel" / "__init__.py",
    ]
    forbidden = ("quantagent.agents", "quantagent.agents.llm", "openai", "anthropic")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in forbidden:
                        assert not alias.name.startswith(bad), f"{path}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                for bad in forbidden:
                    assert not node.module.startswith(bad), f"{path}: from {node.module}"
