"""Unit tests for equal-weight portfolio construction (W7)."""

from __future__ import annotations

import pytest

from quantagent.core.market import load_market_config
from quantagent.decision.portfolio import (
    CandidateMeta,
    PortfolioConfig,
    build_equal_weight_portfolio,
    round_weights_to_lots,
)
from quantagent.decision.portfolio.config import SelectionConfig, WeightingConfig


def test_equal_weight_top_n() -> None:
    scores = {f"S{i:02d}": 0.9 - i * 0.01 for i in range(20)}
    cfg = PortfolioConfig(
        selection=SelectionConfig(top_n=5, min_score=0.5),
        weighting=WeightingConfig(method="equal", max_gross_exposure=0.90, min_cash=0.10),
    )
    result = build_equal_weight_portfolio(scores, cfg=cfg)
    assert len(result.selected) == 5
    assert result.selected[0] == "S00"
    assert abs(sum(result.weights.values()) - 0.90) < 1e-9
    for w in result.weights.values():
        assert abs(w - 0.18) < 1e-9
    assert abs(result.cash_weight - 0.10) < 1e-9


def test_min_score_allows_empty() -> None:
    scores = {"A": 0.40, "B": 0.30}
    cfg = PortfolioConfig(selection=SelectionConfig(top_n=10, min_score=0.55))
    result = build_equal_weight_portfolio(scores, cfg=cfg)
    assert result.selected == []
    assert result.cash_weight == 1.0
    assert result.excluded["A"] == "below_min_score"


def test_exclusion_st_and_suspended() -> None:
    scores = {"A": 0.9, "B": 0.8, "C": 0.7}
    meta = {
        "A": CandidateMeta(symbol="A", is_st=True),
        "B": CandidateMeta(symbol="B", is_suspended=True),
        "C": CandidateMeta(symbol="C"),
    }
    cfg = PortfolioConfig(selection=SelectionConfig(top_n=10, min_score=0.5))
    result = build_equal_weight_portfolio(scores, meta=meta, cfg=cfg)
    assert result.selected == ["C"]
    assert result.excluded["A"] == "is_st"
    assert result.excluded["B"] == "is_suspended"


def test_lot_rounding_residual_to_cash() -> None:
    market = load_market_config("CN")
    weights = {"600000.SH": 0.5}
    prices = {"600000.SH": 33.0}  # 0.5 * 100_000 / 33 ≈ 1515 → floor 1500
    lot_w, cash = round_weights_to_lots(
        weights, prices=prices, total_value=100_000.0, market=market
    )
    assert lot_w["600000.SH"] == pytest.approx(1500 * 33 / 100_000)
    assert cash == pytest.approx(1.0 - lot_w["600000.SH"])
