"""Backtest package (P0 Buy&Hold, P1 single-factor, P4 Top-N portfolio)."""

from quantagent.backtest.engine import BacktestResult, BuyAndHoldConfig, BuyAndHoldEngine
from quantagent.backtest.portfolio import L2TopNBacktest, L2TopNConfig, PortfolioBacktestResult
from quantagent.backtest.report import (
    BiasCheckInputs,
    MatchingAssumptionStatus,
    render_portfolio_backtest_report,
    write_portfolio_backtest_report,
)
from quantagent.backtest.single_factor import (
    SingleFactorBacktest,
    SingleFactorBacktestConfig,
    SingleFactorBacktestResult,
)

__all__ = [
    "BiasCheckInputs",
    "BuyAndHoldConfig",
    "BuyAndHoldEngine",
    "BacktestResult",
    "L2TopNBacktest",
    "L2TopNConfig",
    "MatchingAssumptionStatus",
    "PortfolioBacktestResult",
    "SingleFactorBacktest",
    "SingleFactorBacktestConfig",
    "SingleFactorBacktestResult",
    "render_portfolio_backtest_report",
    "write_portfolio_backtest_report",
]
