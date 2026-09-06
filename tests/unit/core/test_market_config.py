"""Unit tests for MarketConfig loading (W7)."""

from __future__ import annotations

from quantagent.core.market import load_market_config


def test_load_cn_market_config() -> None:
    cfg = load_market_config("CN")
    assert cfg.market == "CN"
    assert cfg.same_day_sell_allowed is False
    assert cfg.settlement == "T+1"
    assert cfg.min_lot_buy == 100
    assert cfg.lot_size("star") == 200
    assert cfg.lot_size("main") == 100
    assert cfg.fees.stamp_duty_sell == 0.001
    assert cfg.slippage.max_volume_share == 0.05
    fees = cfg.estimate_fees(side="sell", notional=100_000.0, quantity=1000)
    assert fees > 100.0  # stamp 100 + commission
