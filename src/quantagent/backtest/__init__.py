"""Backtest package (P0 Buy&Hold, P1 single-factor, P4 Top-N portfolio)."""

from quantagent.backtest.engine import BacktestResult, BuyAndHoldConfig, BuyAndHoldEngine
from quantagent.backtest.controls import ControlSuiteResult, run_control_suite
from quantagent.backtest.l2_panel import (
    CSI300_L2_BACKTEST_END,
    CSI300_L2_BACKTEST_START,
    RealL2TopNPanel,
    build_real_l2_topn_panel,
)
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
    "CSI300_L2_BACKTEST_END",
    "CSI300_L2_BACKTEST_START",
    "ControlSuiteResult",
    "L2TopNBacktest",
    "L2TopNConfig",
    "MatchingAssumptionStatus",
    "PortfolioBacktestResult",
    "RealL2TopNPanel",
    "SingleFactorBacktest",
    "SingleFactorBacktestConfig",
    "SingleFactorBacktestResult",
    "build_real_l2_topn_panel",
    "render_portfolio_backtest_report",
    "run_control_suite",
    "write_portfolio_backtest_report",
]
