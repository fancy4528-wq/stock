"""Unit tests for Buy&Hold metrics."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.backtest.engine import BuyAndHoldEngine, compute_metrics


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
    assert result.metrics.n_days == 3
    assert abs(result.metrics.total_return - 0.05) < 1e-9
    assert result.metrics.max_drawdown < 0
