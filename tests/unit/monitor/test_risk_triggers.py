"""Unit tests: B-class risk triggers."""

from __future__ import annotations

from datetime import date

from quantagent.monitor.triggers.risk import evaluate_risk_triggers
from quantagent.monitor.types import QuoteSnapshot
from quantagent.positions.types import ManualPositionBook, PositionLot


def test_single_weight_and_cash_and_sector() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        cash=1000.0,  # tiny cash → low cash_ratio
        peak_nav=1_000_000.0,
        positions=[
            PositionLot(
                symbol="AAA.SH",
                name="甲",
                industry="食品饮料",
                quantity=900,
                avg_cost=100,
                entry_date=date(2026, 1, 1),
            ),
            PositionLot(
                symbol="BBB.SZ",
                name="乙",
                industry="食品饮料",
                quantity=100,
                avg_cost=100,
                entry_date=date(2026, 1, 1),
            ),
        ],
    )
    quotes = {
        "AAA.SH": QuoteSnapshot(symbol="AAA.SH", last=100, prev_close=100),
        "BBB.SZ": QuoteSnapshot(symbol="BBB.SZ", last=100, prev_close=100),
    }
    # MV = 1000 + 900*100 + 100*100 = 101000; AAA weight ≈ 0.89
    codes = {h.code for h in evaluate_risk_triggers(book, quotes)}
    assert "RISK_SINGLE_WEIGHT" in codes
    assert "RISK_SECTOR_CONCENTRATION" in codes
    assert "RISK_CASH_LOW" in codes


def test_portfolio_drawdown_and_daily_loss() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        cash=0,
        peak_nav=200_000.0,
        positions=[
            PositionLot(
                symbol="AAA.SH",
                quantity=1000,
                avg_cost=100,
                entry_date=date(2026, 1, 1),
            )
        ],
    )
    quotes = {
        "AAA.SH": QuoteSnapshot(symbol="AAA.SH", last=80, prev_close=100),
    }
    codes = {h.code for h in evaluate_risk_triggers(book, quotes)}
    assert "RISK_PORTFOLIO_DRAWDOWN" in codes
    assert "RISK_DAILY_LOSS" in codes


def test_dd_005_floor() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        cash=50_000,
        positions=[
            PositionLot(
                symbol="AAA.SH",
                name="深亏",
                quantity=100,
                avg_cost=100,
                entry_date=date(2026, 1, 1),
            )
        ],
    )
    quotes = {
        "AAA.SH": QuoteSnapshot(symbol="AAA.SH", last=70, prev_close=71),
    }
    codes = {h.code for h in evaluate_risk_triggers(book, quotes)}
    assert "RISK_DD_005" in codes
