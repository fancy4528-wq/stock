"""Unit tests for Buy&Hold metrics and SimulatedBroker constraints."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from quantagent.backtest.engine import BuyAndHoldEngine, compute_metrics
from quantagent.shared.errors import QuantAgentError


def test_compute_metrics_simple_doubling() -> None:
    dates = [date(2020, 1, 1), date(2021, 1, 1)]
    closes = [100.0, 200.0]
    m = compute_metrics(dates, closes)
    assert abs(m.total_return - 1.0) < 1e-9
    assert m.cagr > 0.9
    assert m.max_drawdown == 0.0


def test_buy_and_hold_from_frame() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)],
            "close": [100.0, 110.0, 105.0],
        }
    )
    result = BuyAndHoldEngine().run_from_frame(df, symbol="000300.SH")
    assert result.constraints_applied is False
    assert result.metrics.n_days == 3
    assert abs(result.metrics.total_return - 0.05) < 1e-9
    assert result.metrics.max_drawdown < 0


def test_buy_and_hold_constrained_fees_and_t1() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)],
            "open": [10.0, 10.5, 10.2],
            "high": [10.2, 10.6, 10.4],
            "low": [9.8, 10.3, 10.0],
            "close": [10.0, 10.5, 10.2],
            "volume": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "is_suspended": [False, False, False],
            "is_limit_up": [False, False, False],
            "is_limit_down": [False, False, False],
        }
    )
    result = BuyAndHoldEngine().run_from_frame(
        df,
        symbol="600000.SH",
        apply_constraints=True,
        initial_cash=100_000.0,
        probe_t1=True,
    )
    assert result.constraints_applied is True
    assert result.total_fees > 0
    reasons = {u["reason"] for u in result.unfilled}
    assert "t1_not_sellable" in reasons
    # NAV after fees should underperform raw close path slightly.
    naked = BuyAndHoldEngine().run_from_frame(df, symbol="600000.SH", apply_constraints=False)
    assert result.metrics.total_return < naked.metrics.total_return + 1e-12


def test_buy_and_hold_constrained_skips_suspend_then_limit() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)],
            "open": [10.0, 10.0, 10.0],
            "high": [10.0, 10.0, 10.0],
            "low": [10.0, 10.0, 10.0],
            "close": [10.0, 10.5, 11.0],
            "volume": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "is_suspended": [True, False, False],
            "is_limit_up": [False, True, False],
            "is_limit_down": [False, False, False],
        }
    )
    result = BuyAndHoldEngine().run_from_frame(
        df,
        symbol="600000.SH",
        apply_constraints=True,
        initial_cash=100_000.0,
        probe_t1=False,
    )
    assert result.constraints_applied is True
    reasons = {u["reason"] for u in result.unfilled}
    assert "suspended" in reasons
    assert "limit_up_cannot_buy" in reasons
    # Entry on day 3 only; equity still has 3 marks.
    assert result.metrics.n_days == 3


def test_buy_and_hold_constrained_never_enters() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 2), date(2020, 1, 3)],
            "open": [10.0, 10.0],
            "close": [10.0, 10.0],
            "volume": [1_000_000.0, 1_000_000.0],
            "is_suspended": [True, True],
            "is_limit_up": [False, False],
            "is_limit_down": [False, False],
        }
    )
    with pytest.raises(QuantAgentError, match="never entered"):
        BuyAndHoldEngine().run_from_frame(
            df,
            symbol="600000.SH",
            apply_constraints=True,
            probe_t1=False,
        )
