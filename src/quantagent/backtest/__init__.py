"""Backtest package (P0: Buy&Hold baseline; P1: single-factor stub)."""

from quantagent.backtest.engine import BacktestResult, BuyAndHoldConfig, BuyAndHoldEngine
from quantagent.backtest.single_factor import (
    SingleFactorBacktest,
    SingleFactorBacktestConfig,
    SingleFactorBacktestResult,
)

__all__ = [
    "BuyAndHoldConfig",
    "BuyAndHoldEngine",
    "BacktestResult",
    "SingleFactorBacktest",
    "SingleFactorBacktestConfig",
    "SingleFactorBacktestResult",
]
