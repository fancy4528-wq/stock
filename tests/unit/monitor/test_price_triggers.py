"""Unit tests: A-class price triggers (zero LLM)."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from quantagent.monitor.exit_policy import (
    ExitPolicy,
    StopLossPolicy,
    TakeProfitPolicy,
    load_exit_policy,
)
from quantagent.monitor.triggers import run_price_triggers
from quantagent.monitor.types import QuoteSnapshot
from quantagent.positions.types import ManualPositionBook, PositionLot, WatchlistItem
from quantagent.shared.errors import ConfigError


def _book_with(
    *,
    symbol: str = "600519.SH",
    avg_cost: float = 100.0,
    qty: float = 100.0,
    entry_high: float | None = 120.0,
) -> ManualPositionBook:
    return ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        cash=10_000,
        positions=[
            PositionLot(
                symbol=symbol,
                name="测试",
                quantity=qty,
                avg_cost=avg_cost,
                entry_date=date(2026, 7, 1),
                entry_high=entry_high,
            )
        ],
    )


def test_load_exit_policy() -> None:
    pol = load_exit_policy("CN")
    assert pol.stop_loss.enabled
    assert pol.stop_loss.threshold == -0.10


def test_exit_policy_bounds_reject() -> None:
    with pytest.raises(ConfigError):
        ExitPolicy(stop_loss=StopLossPolicy(threshold=-0.80))


def test_stop_loss_fires() -> None:
    book = _book_with(avg_cost=100.0, entry_high=100.0)
    quotes = {
        "600519.SH": QuoteSnapshot(symbol="600519.SH", last=88.0, prev_close=90.0)
    }
    hits = run_price_triggers(book, quotes)
    codes = {h.code for h in hits}
    assert "PX_STOP_LOSS" in codes
    assert all(h.cost_usd == 0 for h in hits)
    assert all(h.analysis_level == "L1" for h in hits)


def test_stop_loss_does_not_fire_above_threshold() -> None:
    book = _book_with(avg_cost=100.0, entry_high=100.0)
    quotes = {
        "600519.SH": QuoteSnapshot(symbol="600519.SH", last=95.0, prev_close=96.0)
    }
    hits = run_price_triggers(book, quotes)
    assert "PX_STOP_LOSS" not in {h.code for h in hits}


def test_trailing_stop() -> None:
    pol = ExitPolicy(
        stop_loss=StopLossPolicy(type="trailing", threshold=-0.10, trail_pct=0.15)
    )
    book = _book_with(avg_cost=100.0, entry_high=120.0)
    quotes = {
        "600519.SH": QuoteSnapshot(symbol="600519.SH", last=100.0, prev_close=101.0)
    }
    hits = run_price_triggers(book, quotes, policy=pol)
    assert "PX_TRAILING_STOP" in {h.code for h in hits}
    assert "PX_STOP_LOSS" not in {h.code for h in hits}


def test_take_profit_staged() -> None:
    book = _book_with(avg_cost=100.0, entry_high=130.0)
    quotes = {
        "600519.SH": QuoteSnapshot(symbol="600519.SH", last=125.0, prev_close=124.0)
    }
    hits = run_price_triggers(book, quotes)
    assert "PX_TAKE_PROFIT" in {h.code for h in hits}


def test_limit_down_and_suspended() -> None:
    book = _book_with(avg_cost=100.0, entry_high=100.0)
    quotes = {
        "600519.SH": QuoteSnapshot(
            symbol="600519.SH",
            last=100.0,
            is_limit_down=True,
            is_suspended=True,
        )
    }
    codes = {h.code for h in run_price_triggers(book, quotes)}
    assert "PX_LIMIT_DOWN" in codes
    assert "PX_SUSPENDED" in codes


def test_vol_spike() -> None:
    book = _book_with(avg_cost=100.0, entry_high=100.0)
    quotes = {
        "600519.SH": QuoteSnapshot(
            symbol="600519.SH",
            last=106.0,
            prev_close=100.0,
            volume=4000,
            volume_avg_5d=1000,
        )
    }
    assert "PX_VOL_SPIKE" in {h.code for h in run_price_triggers(book, quotes)}


def test_break_ma60() -> None:
    book = _book_with(avg_cost=100.0, entry_high=100.0)
    quotes = {
        "600519.SH": QuoteSnapshot(
            symbol="600519.SH",
            last=99.0,
            prev_close=101.0,
            ma60=100.0,
            prev_ma60=100.0,
        )
    }
    assert "PX_BREAK_MA60" in {h.code for h in run_price_triggers(book, quotes)}


def test_watchlist_target_price() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        positions=[],
        watchlist=[
            WatchlistItem(symbol="300750.SZ", name="宁德", target_price=180.0)
        ],
    )
    quotes = {
        "300750.SZ": QuoteSnapshot(symbol="300750.SZ", last=185.0, prev_close=180.0)
    }
    hits = run_price_triggers(book, quotes)
    assert any(h.code == "PX_TARGET_PRICE" for h in hits)


def test_take_profit_disabled() -> None:
    pol = ExitPolicy(take_profit=TakeProfitPolicy(enabled=False))
    book = _book_with(avg_cost=100.0, entry_high=150.0)
    quotes = {
        "600519.SH": QuoteSnapshot(symbol="600519.SH", last=130.0, prev_close=129.0)
    }
    hits = run_price_triggers(book, quotes, policy=pol)
    assert "PX_TAKE_PROFIT" not in {h.code for h in hits}


def test_price_triggers_have_no_llm_imports() -> None:
    """Architecture: monitor.triggers.price must not import agents/llm."""
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "src" / "quantagent" / "monitor" / "triggers" / "price.py",
        root / "src" / "quantagent" / "monitor" / "triggers" / "registry.py",
        root / "src" / "quantagent" / "monitor" / "triggers" / "base.py",
        root / "src" / "quantagent" / "monitor" / "triggers" / "risk.py",
        root / "src" / "quantagent" / "monitor" / "suppression.py",
        root / "src" / "quantagent" / "monitor" / "engine.py",
        root / "src" / "quantagent" / "positions" / "manual.py",
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
