"""Unit tests for real L2 Top-N panel helpers (no DB)."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.backtest.l2_panel import bars_from_prices, scores_from_l2_panel
from quantagent.quant.models.baseline import COMBO_EQUAL


def test_scores_from_l2_panel_membership_filter() -> None:
    d0, d1 = date(2024, 1, 2), date(2024, 1, 3)
    panel = pl.DataFrame(
        {
            "trade_date": [d0, d0, d1, d1],
            "symbol": ["AAA", "BBB", "AAA", "CCC"],
            COMBO_EQUAL: [0.9, 0.1, 0.8, 0.7],
        }
    )
    membership = {
        d0: frozenset({"AAA", "BBB"}),
        d1: frozenset({"CCC"}),  # AAA left the index
    }
    scores = scores_from_l2_panel(
        panel, start=d0, end=d1, membership=membership
    )
    assert scores[d0] == {"AAA": 0.9, "BBB": 0.1}
    assert scores[d1] == {"CCC": 0.7}


def test_scores_from_l2_panel_window_and_nulls() -> None:
    d0, d1, d2 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)
    panel = pl.DataFrame(
        {
            "trade_date": [d0, d1, d2],
            "symbol": ["AAA", "AAA", "AAA"],
            COMBO_EQUAL: [0.5, None, 0.6],
        }
    )
    scores = scores_from_l2_panel(panel, start=d1, end=d2, membership=None)
    assert d0 not in scores
    assert d1 not in scores  # null score dropped
    assert scores[d2] == {"AAA": 0.6}


def test_bars_from_prices_maps_limits() -> None:
    d0 = date(2024, 1, 2)
    prices = pl.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": [d0],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1_000_000.0],
            "amount": [1e7],
            "is_limit_up": [True],
            "is_suspended": [False],
            "is_limit_down": [False],
        }
    )
    bars = bars_from_prices(prices, start=d0, end=d0)
    assert len(bars) == 1
    assert bars[0].symbol == "AAA"
    assert bars[0].is_limit_up is True
    assert bars[0].close == 10.5
