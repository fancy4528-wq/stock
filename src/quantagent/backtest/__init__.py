"""Backtest package (P0 Buy&Hold, P1 single-factor, P4 Top-N portfolio)."""

from quantagent.backtest.engine import BacktestResult, BuyAndHoldConfig, BuyAndHoldEngine
from quantagent.backtest.portfolio import L2TopNBacktest, L2TopNConfig, PortfolioBacktestResult
from quantagent.backtest.single_factor import (
    SingleFactorBacktest,
    SingleFactorBacktestConfig,
    SingleFactorBacktestResult,
)

__all__ = [
    "BuyAndHoldConfig",
    "BuyAndHoldEngine",
    "BacktestResult",
    "L2TopNBacktest",
    "L2TopNConfig",
    "PortfolioBacktestResult",
    "SingleFactorBacktest",
    "SingleFactorBacktestConfig",
    "SingleFactorBacktestResult",
]
