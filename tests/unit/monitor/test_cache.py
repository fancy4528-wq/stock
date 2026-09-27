"""Unit tests: L2 analysis result cache (content_hash + holdings_hash)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.client import EchoLLMClient
from quantagent.agents.llm.config import BudgetConfig, LLMConfig, TierConfig
from quantagent.monitor.cache import (
    AnalysisCache,
    L2CachedTriage,
    holdings_hash,
    l2_cache_key,
    resolve_content_hash,
)
from quantagent.monitor.funnel.l2_triage import refine_news_hits_with_l2
from quantagent.monitor.types import TriggerHit


def _tier() -> TierConfig:
    return TierConfig(
        model="test",
        max_tokens_out=256,
        input_usd_per_1m=1.0,
        output_usd_per_1m=1.0,
    )


def _budget() -> TokenBudget:
    cfg = LLMConfig(
        tiers={"small": _tier(), "medium": _tier(), "large": _tier()},
        budget=BudgetConfig(
            daily_usd_limit=10.0,
            monthly_usd_limit=100.0,
            allocations={
                "daily_research": 1.0,
                "monitoring": 1.0,
                "news_extraction": 1.0,
                "adhoc": 1.0,
            },
            on_exceed={
                "daily_research": "degrade",
                "monitoring": "l1_only",
                "news_extraction": "skip",
                "adhoc": "abort",
            },
        ),
    )
    return TokenBudget(llm_config=cfg)


def _hit(*, code: str, title: str, content_hash: str) -> TriggerHit:
    return TriggerHit(
        code=code,
        severity="high",
        symbol="600519.SH",
        title="NEWS_HIGH",
        message=title,
        evidence={
            "title": title,
            "summary": "摘要",
            "content_hash": content_hash,
            "mentioned_symbols": ["600519.SH"],
            "l1_severity": "high",
        },
    )


def test_holdings_hash_order_independent() -> None:
    a = holdings_hash(["600519.SH", "000001.SZ"])
    b = holdings_hash(["000001.SZ", "600519.SH"])
    assert a == b
    assert holdings_hash(["600519.SH"]) != a


def test_l2_cache_key_format() -> None:
    assert l2_cache_key("abc", "def") == "l2:abc:def"


def test_resolve_content_hash_prefers_explicit() -> None:
    assert resolve_content_hash(explicit="feed-hash", title="t") == "feed-hash"
    h = resolve_content_hash(explicit=None, title="t", summary="s")
    assert len(h) == 64


def test_memory_get_set_and_ttl(tmp_path: Path) -> None:
    cache = AnalysisCache(ttl_seconds=10, path=None)
    row = L2CachedTriage(rel=True, sym=["600519.SH"], dir="neg", urg="today", deep=True)
    cache.set_l2("ch1", "hh1", row, now=1000.0)
    assert cache.get_l2("ch1", "hh1", now=1005.0) == row
    assert cache.get_l2("ch1", "hh1", now=1011.0) is None  # expired
    assert cache.stats.hits == 1
    assert cache.stats.misses >= 1


def test_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = AnalysisCache(ttl_seconds=3600, path=path)
    row = L2CachedTriage(rel=False)
    cache.set_l2("ch", holdings_hash(["600519.SH"]), row)
    assert path.is_file()

    loaded = AnalysisCache(ttl_seconds=3600, path=path)
    got = loaded.get_l2("ch", holdings_hash(["600519.SH"]))
    assert got is not None and got.rel is False


def test_refine_cache_hit_skips_llm() -> None:
    cache = AnalysisCache(ttl_seconds=3600, path=None)
    names = {"600519.SH": "茅台"}
    hit = _hit(code="NEWS_HIGH/1", title="茅台重大合同", content_hash="hash-a")
    payload = (
        '[{"i":1,"rel":true,"sym":["600519.SH"],"dir":"pos","urg":"today","deep":false}]'
    )

    out1, stats1 = asyncio.run(
        refine_news_hits_with_l2(
            [hit],
            name_by_symbol=names,
            llm=EchoLLMClient(payload),
            budget=_budget(),
            cache=cache,
        )
    )
    assert stats1.mode == "llm"
    assert stats1.cache_misses == 1 and stats1.cache_hits == 0
    assert stats1.cost_usd > 0
    assert len(out1) == 1
    assert len(cache) == 1

    # Second pass: poison LLM would flip to rel=false if consulted
    out2, stats2 = asyncio.run(
        refine_news_hits_with_l2(
            [hit],
            name_by_symbol=names,
            llm=EchoLLMClient('[{"i":1,"rel":false}]'),
            budget=_budget(),
            cache=cache,
        )
    )
    assert stats2.mode == "cache"
    assert stats2.cache_hits == 1 and stats2.cache_misses == 0
    assert stats2.cost_usd == 0.0
    assert len(out2) == 1
    assert out2[0].evidence["l2_cache_hit"] is True
    assert out2[0].evidence["l2_dir"] == "pos"


def test_holdings_change_invalidates_cache() -> None:
    cache = AnalysisCache(ttl_seconds=3600, path=None)
    hit = _hit(code="NEWS_HIGH/1", title="茅台重大合同", content_hash="hash-b")
    payload = (
        '[{"i":1,"rel":true,"sym":["600519.SH"],"dir":"neg","urg":"today","deep":false}]'
    )
    asyncio.run(
        refine_news_hits_with_l2(
            [hit],
            name_by_symbol={"600519.SH": "茅台"},
            llm=EchoLLMClient(payload),
            budget=_budget(),
            cache=cache,
        )
    )
    out, stats = asyncio.run(
        refine_news_hits_with_l2(
            [hit],
            name_by_symbol={"600519.SH": "茅台", "000001.SZ": "平安"},
            llm=EchoLLMClient('[{"i":1,"rel":false}]'),
            budget=_budget(),
            cache=cache,
        )
    )
    assert stats.cache_hits == 0
    assert stats.mode == "llm"
    assert out == []  # poison LLM dropped it — proves cache miss


def test_heuristic_not_cached() -> None:
    from quantagent.agents.llm.client import NullLLMClient

    cache = AnalysisCache(ttl_seconds=3600, path=None)
    hit = _hit(code="NEWS_HIGH/1", title="x", content_hash="hash-c")
    asyncio.run(
        refine_news_hits_with_l2(
            [hit],
            name_by_symbol={"600519.SH": "茅台"},
            llm=NullLLMClient(),
            budget=_budget(),
            cache=cache,
        )
    )
    assert len(cache) == 0


def test_purge_expired() -> None:
    cache = AnalysisCache(ttl_seconds=1, path=None)
    cache.set_l2("a", "h", L2CachedTriage(rel=True), now=time.time() - 10)
    assert cache.purge_expired() == 1
    assert len(cache) == 0
