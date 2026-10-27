"""Unit tests for shadow fused / fused_norisk helpers."""

from __future__ import annotations

from datetime import date

from quantagent.evaluation.shadow.fusion_signals import (
    apply_risk_filter,
    fuse_quant_agent_scores,
    security_context_from_bars,
    top_n_symbols,
)
from quantagent.execution.broker.simulated import PriceBar


def test_fuse_quant_agent_scores_maps_stock() -> None:
    scores = fuse_quant_agent_scores(
        {"A": 1.0, "B": 0.0},
        {"A": 0.0, "B": 1.0},
    )
    assert set(scores) == {"A", "B"}
    # Opposite ranks → equal fused after rank+equal weight
    assert abs(scores["A"] - scores["B"]) < 1e-9


def test_fuse_quant_only() -> None:
    scores = fuse_quant_agent_scores({"A": 0.9, "B": 0.1}, {})
    assert scores["A"] > scores["B"]


def test_top_n_symbols() -> None:
    assert top_n_symbols({"A": 1, "B": 3, "C": 2}, 2) == ["B", "C"]
    assert top_n_symbols({}, 5) == []


def test_apply_risk_drops_limit_up() -> None:
    as_of = date(2026, 9, 1)
    bars = [
        PriceBar(
            symbol="A",
            trade_date=as_of,
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1e6,
            amount=80_000_000,
            is_limit_up=True,
        ),
        PriceBar(
            symbol="B",
            trade_date=as_of,
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1e6,
            amount=80_000_000,
        ),
    ]
    kept, notes = apply_risk_filter(
        ["A", "B"],
        bars=bars,
        as_of=as_of,
        total_value=1_000_000,
    )
    assert "A" not in kept
    assert "B" in kept
    assert any(n.startswith("risk:") for n in notes)
    assert any("EXE_002" in n for n in notes)


def test_security_context_from_bars() -> None:
    as_of = date(2026, 9, 1)
    bars = [
        PriceBar(
            symbol="A",
            trade_date=as_of,
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1e6,
            amount=0,
            is_suspended=True,
        )
    ]
    ctx = security_context_from_bars(bars)
    assert ctx["A"].is_suspended is True
    assert ctx["A"].avg_amount_20d == 10_000_000.0
