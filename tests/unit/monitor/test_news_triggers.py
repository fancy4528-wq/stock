"""Unit tests: D-class news triggers (L1)."""

from __future__ import annotations

import ast
from pathlib import Path

from quantagent.monitor.funnel.entity_matcher import EntityAliasConfig
from quantagent.monitor.funnel.keywords import KeywordConfig
from quantagent.monitor.funnel.l1_rules import L1Filter
from quantagent.monitor.triggers.news import (
    NewsFeedItem,
    evaluate_news_triggers,
)


def _l1() -> L1Filter:
    return L1Filter(
        entity_cfg=EntityAliasConfig(
            aliases={"600519.SH": ["茅台", "贵州茅台"]},
            industries={"食品饮料": ["白酒"]},
        ),
        keyword_cfg=KeywordConfig(
            critical=["立案调查"],
            high=["重大合同"],
            medium=["机构调研"],
        ),
    )


def test_news_trigger_pass_and_stats() -> None:
    items = [
        NewsFeedItem(title="茅台签署重大合同", news_id=1, source="cls"),
        NewsFeedItem(title="无关快讯无关键词", news_id=2, source="cls"),
        NewsFeedItem(title="茅台举办品牌活动", news_id=3, source="cls"),
    ]
    hits, stats = evaluate_news_triggers(
        items, {"600519.SH"}, name_by_symbol={"600519.SH": "茅台"}, l1=_l1()
    )
    assert stats.scanned == 3
    assert stats.passed == 1
    assert stats.drop_no_relevance == 1
    assert stats.drop_low_severity == 1
    assert len(hits) == 1
    assert hits[0].code.startswith("NEWS_HIGH/")
    assert hits[0].symbol == "600519.SH"
    assert hits[0].cost_usd == 0.0
    assert hits[0].analysis_level == "L1"
    assert hits[0].evidence["mentioned_symbols"] == ["600519.SH"]


def test_news_trigger_industry_path() -> None:
    items = [NewsFeedItem(title="白酒板块机构调研增多", news_id=4)]
    hits, stats = evaluate_news_triggers(
        items,
        {"600519.SH"},
        industry_by_symbol={"600519.SH": "食品饮料"},
        l1=_l1(),
    )
    assert stats.passed == 1
    assert hits[0].evidence["match_kind"] == "industry"


def test_news_triggers_have_no_agents_imports() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "src" / "quantagent" / "monitor" / "triggers" / "news.py",
        root / "src" / "quantagent" / "monitor" / "news_fetch.py",
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
