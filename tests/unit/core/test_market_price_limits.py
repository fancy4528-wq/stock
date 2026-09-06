"""Unit tests for MarketConfig price-limit rule matching."""

from __future__ import annotations

from quantagent.core.market import load_market_config


def test_cn_price_limits_by_board_and_st() -> None:
    cfg = load_market_config("CN")
    assert cfg.price_limits(board="main", is_st=False) == (0.10, -0.10)
    assert cfg.price_limits(board="main", is_st=True) == (0.05, -0.05)
    assert cfg.price_limits(board="star", is_st=False) == (0.20, -0.20)
    assert cfg.price_limits(board="gem", is_st=False) == (0.20, -0.20)
    assert cfg.price_limits(board="bse", is_st=False) == (0.30, -0.30)


def test_cn_st_overrides_board() -> None:
    cfg = load_market_config("CN")
    # is_st rule is listed before board rules in cn.yaml
    assert cfg.price_limits(board="star", is_st=True) == (0.05, -0.05)
