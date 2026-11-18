"""Build AttributionResult from a portfolio backtest + optional inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from quantagent.backtest.portfolio import PortfolioBacktestResult
from quantagent.evaluation.attribution.returns import (
    align_benchmark_returns,
    daily_stock_returns_from_bars,
    decompose_returns,
)
from quantagent.evaluation.attribution.signals import attribute_by_signal
from quantagent.evaluation.attribution.types import AttributionResult
from quantagent.execution.broker.simulated import PriceBar


def attribute_portfolio(
    result: PortfolioBacktestResult,
    *,
    benchmark_returns: Sequence[float] | None = None,
    benchmark_dates: Sequence[date] | None = None,
    benchmark_equity: Sequence[float] | None = None,
    bars: Sequence[PriceBar] | Mapping[date, Sequence[PriceBar]] | None = None,
    stock_returns: Mapping[date, Mapping[str, float]] | None = None,
    industry_map: Mapping[str, str] | None = None,
    signal_returns: Mapping[str, float] | None = None,
    baseline_return: float | None = None,
    fused_return: float | None = None,
) -> AttributionResult:
    """Run §7.1 / §7.2 on a finished ``PortfolioBacktestResult``."""
    if not result.dates or not result.equity_curve or not result.weights_history:
        decomp = decompose_returns(
            dates=[],
            equity=[],
            weights_history=[],
            cash_weights=[],
            daily_fees=[],
            benchmark_returns=[],
        )
        signals, note = attribute_by_signal(
            fused_return=fused_return if fused_return is not None else result.total_return,
            baseline_return=baseline_return,
            signal_returns=signal_returns or {},
        )
        return AttributionResult(returns=decomp, signals=signals, signal_note=note)

    if benchmark_returns is None:
        if benchmark_dates is not None and benchmark_equity is not None:
            bench = align_benchmark_returns(
                result.dates, benchmark_dates, benchmark_equity
            )
        else:
            # Flat benchmark → market/timing near zero; still ties out via residual.
            bench = [0.0] * (len(result.dates) - 1)
    else:
        bench = list(benchmark_returns)

    srets = stock_returns
    if srets is None and bars is not None:
        srets = daily_stock_returns_from_bars(bars)

    decomp = decompose_returns(
        dates=result.dates,
        equity=result.equity_curve,
        weights_history=result.weights_history,
        cash_weights=result.cash_weights,
        daily_fees=result.daily_fees,
        benchmark_returns=bench,
        stock_returns=srets,
        industry_map=industry_map,
        initial_nav=result.initial_nav,
    )
    signals, note = attribute_by_signal(
        fused_return=result.total_return if fused_return is None else fused_return,
        baseline_return=baseline_return,
        signal_returns=signal_returns or {},
    )
    return AttributionResult(returns=decomp, signals=signals, signal_note=note)
