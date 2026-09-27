"""Unit tests: L2 small-model triage (batch + heuristic + refine)."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.client import EchoLLMClient, NullLLMClient
from quantagent.agents.llm.config import BudgetConfig, LLMConfig, TierConfig
from quantagent.monitor.funnel.l2_triage import (
    L2Candidate,
    build_batch_user_prompt,
    chunked,
    heuristic_triage,
    parse_batch_response,
    refine_news_hits_with_l2,
    triage_batch,
)
from quantagent.monitor.types import TriggerHit


def _tier() -> TierConfig:
    return TierConfig(
        model="test",
        max_tokens_out=256,
        input_usd_per_1m=1.0,
        output_usd_per_1m=1.0,
    )


def _budget(*, monitoring: float = 1.0) -> TokenBudget:
    cfg = LLMConfig(
        tiers={"small": _tier(), "medium": _tier(), "large": _tier()},
        budget=BudgetConfig(
            daily_usd_limit=10.0,
            monthly_usd_limit=100.0,
            allocations={
                "daily_research": 1.0,
                "monitoring": monitoring,
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


def test_chunked_and_prompt() -> None:
    items = [L2Candidate(title=f"t{i}") for i in range(12)]
    batches = chunked(items, 5)
    assert len(batches) == 3
    assert len(batches[0]) == 5
    assert len(batches[-1]) == 2
    prompt = build_batch_user_prompt(
        batches[0], name_by_symbol={"600519.SH": "茅台"}, start_index=1
    )
    assert "600519.SH(茅台)" in prompt
    assert "1. 标题: t0" in prompt


def test_parse_batch_response_maps_abbrev() -> None:
    text = (
        '[{"i":1,"rel":false},'
        '{"i":2,"rel":true,"sym":["600519.SH"],"dir":"negative","urg":"today","deep":true}]'
    )
    rows = parse_batch_response(text, batch_size=2, start_index=1)
    assert rows[0].rel is False
    assert rows[1].rel is True
    assert rows[1].dir == "neg"
    assert rows[1].deep is True


def test_parse_missing_row_fail_closed() -> None:
    rows = parse_batch_response('[{"i":1,"rel":true,"sym":["600519.SH"]}]', batch_size=2)
    assert rows[0].rel is True
    assert rows[1].rel is False


def test_heuristic_critical_deep() -> None:
    row = heuristic_triage(
        L2Candidate(title="x", candidate_symbols=["600519.SH"], l1_severity="critical"),
        index=1,
    )
    assert row.rel and row.deep and row.dir == "neg" and row.urg == "immediate"


def test_triage_null_llm_heuristic() -> None:
    cands = [
        L2Candidate(
            title="茅台重大合同",
            candidate_symbols=["600519.SH"],
            l1_severity="high",
        )
    ]
    rows, stats = asyncio.run(
        triage_batch(
            cands,
            name_by_symbol={"600519.SH": "茅台"},
            llm=NullLLMClient(),
            budget=_budget(),
        )
    )
    assert stats.mode == "heuristic"
    assert stats.relevant == 1
    assert rows[0].rel is True
    assert rows[0].urg == "today"


def test_triage_echo_llm() -> None:
    payload = (
        '[{"i":1,"rel":true,"sym":["600519.SH"],"dir":"pos","urg":"today","deep":false},'
        '{"i":2,"rel":false}]'
    )
    cands = [
        L2Candidate(title="a", candidate_symbols=["600519.SH"], l1_severity="high"),
        L2Candidate(title="b", candidate_symbols=["600519.SH"], l1_severity="medium"),
    ]
    rows, stats = asyncio.run(
        triage_batch(
            cands,
            name_by_symbol={"600519.SH": "茅台"},
            llm=EchoLLMClient(payload),
            budget=_budget(),
            batch_size=10,
        )
    )
    assert stats.mode == "llm"
    assert stats.cost_usd > 0
    assert rows[0].rel is True and rows[0].dir == "pos"
    assert rows[1].rel is False
    assert stats.relevant == 1 and stats.dropped == 1


def test_budget_l1_passthrough_keeps_hits() -> None:
    hit = TriggerHit(
        code="NEWS_HIGH/1",
        severity="high",
        symbol="600519.SH",
        title="NEWS_HIGH",
        message="msg",
        analysis_level="L1",
        evidence={
            "title": "茅台重大合同",
            "summary": "签署合同",
            "mentioned_symbols": ["600519.SH"],
            "l1_severity": "high",
        },
    )
    # Tiny monitoring pool → first reserve fails → l1_passthrough
    tiny = _budget(monitoring=0.0000001)
    out, stats = asyncio.run(
        refine_news_hits_with_l2(
            [hit],
            name_by_symbol={"600519.SH": "茅台"},
            llm=EchoLLMClient('[{"i":1,"rel":false}]'),
            budget=tiny,
        )
    )
    assert stats.mode == "l1_passthrough"
    assert len(out) == 1
    assert out[0].analysis_level == "L1"


def test_refine_drops_irrelevant() -> None:
    hits = [
        TriggerHit(
            code="NEWS_HIGH/1",
            severity="high",
            symbol="600519.SH",
            title="NEWS_HIGH",
            message="a",
            evidence={
                "title": "茅台重大合同",
                "mentioned_symbols": ["600519.SH"],
                "l1_severity": "high",
            },
        ),
        TriggerHit(
            code="NEWS_MEDIUM/2",
            severity="medium",
            symbol="600519.SH",
            title="NEWS_MEDIUM",
            message="b",
            evidence={
                "title": "噪音",
                "mentioned_symbols": ["600519.SH"],
                "l1_severity": "medium",
            },
        ),
    ]
    payload = (
        '[{"i":1,"rel":true,"sym":["600519.SH"],"dir":"pos","urg":"today","deep":false},'
        '{"i":2,"rel":false}]'
    )
    out, stats = asyncio.run(
        refine_news_hits_with_l2(
            hits,
            name_by_symbol={"600519.SH": "茅台"},
            llm=EchoLLMClient(payload),
            budget=_budget(),
        )
    )
    assert len(out) == 1
    assert out[0].code == "NEWS_HIGH/1"
    assert out[0].analysis_level == "L2"
    assert out[0].evidence["l2_dir"] == "pos"
    assert stats.dropped == 1


def test_price_and_l1_still_forbid_l2_imports() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "src" / "quantagent" / "monitor" / "triggers" / "price.py",
        root / "src" / "quantagent" / "monitor" / "triggers" / "risk.py",
        root / "src" / "quantagent" / "monitor" / "funnel" / "l1_rules.py",
        root / "src" / "quantagent" / "monitor" / "triggers" / "news.py",
    ]
    forbidden = (
        "quantagent.agents",
        "quantagent.monitor.funnel.l2_triage",
        "openai",
        "anthropic",
    )
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

    # cache.py / budget.py must stay LLM-free (zero-cost boundary)
    for name in ("cache.py", "budget.py"):
        src = root / "src" / "quantagent" / "monitor" / name
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("quantagent.agents"), name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("quantagent.agents"), name
                assert not node.module.startswith("quantagent.monitor.funnel.l2"), name
