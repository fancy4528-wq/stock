"""Unit tests: L1 entity alias matcher."""

from __future__ import annotations

from quantagent.monitor.funnel.entity_matcher import EntityAliasConfig, EntityMatcher


def _cfg() -> EntityAliasConfig:
    return EntityAliasConfig(
        aliases={
            "600519.SH": ["贵州茅台", "茅台酒", "茅台"],
            "000858.SZ": ["五粮液"],
            "300750.SZ": ["宁德时代", "CATL"],
        },
        industries={
            "食品饮料": ["白酒板块", "白酒", "食品饮料"],
            "电力设备": ["动力电池", "锂电"],
        },
    )


def test_match_entity_prefers_longer_alias() -> None:
    m = EntityMatcher(_cfg())
    hits = m.match_entities(
        "贵州茅台股价波动",
        {"600519.SH", "000858.SZ"},
    )
    assert hits == ["600519.SH"]


def test_match_entity_ascii_case_insensitive() -> None:
    m = EntityMatcher(_cfg())
    hits = m.match_entities("catl expands overseas", {"300750.SZ", "600519.SH"})
    assert hits == ["300750.SZ"]


def test_match_entity_uses_holding_name_fallback() -> None:
    m = EntityMatcher(EntityAliasConfig())
    hits = m.match_entities(
        "关于五粮液的机构观点",
        {"000858.SZ"},
        name_by_symbol={"000858.SZ": "五粮液"},
    )
    assert hits == ["000858.SZ"]


def test_match_entity_ignores_non_holdings() -> None:
    m = EntityMatcher(_cfg())
    hits = m.match_entities("茅台大涨", {"000858.SZ"})
    assert hits == []


def test_match_industry_maps_to_holdings() -> None:
    m = EntityMatcher(_cfg())
    hits = m.match_industries(
        "白酒板块集体回调",
        {"600519.SH", "000858.SZ", "300750.SZ"},
        industry_by_symbol={
            "600519.SH": "食品饮料",
            "000858.SZ": "食品饮料",
            "300750.SZ": "电力设备",
        },
    )
    assert hits == ["000858.SZ", "600519.SH"]


def test_match_entity_before_industry() -> None:
    m = EntityMatcher(_cfg())
    mentioned, kind = m.match(
        "茅台与白酒板块同日下跌",
        {"600519.SH", "000858.SZ"},
        industry_by_symbol={
            "600519.SH": "食品饮料",
            "000858.SZ": "食品饮料",
        },
    )
    assert kind == "entity"
    assert mentioned == ["600519.SH"]


def test_load_default_entity_aliases_has_maotai() -> None:
    from quantagent.monitor.funnel.entity_matcher import load_entity_aliases

    cfg = load_entity_aliases()
    assert "600519.SH" in cfg.aliases
    assert any("茅台" in a for a in cfg.aliases["600519.SH"])
    assert "食品饮料" in cfg.industries
