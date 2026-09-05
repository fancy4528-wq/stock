"""Future-function sentinel helpers for backtests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from quantagent.backtest.engine import BacktestResult


def assert_metrics_unchanged(
    baseline: BacktestResult,
    polluted: BacktestResult,
    *,
    tol: float = 1e-12,
) -> None:
    """Fail if injecting future data changed historical backtest metrics."""
    b, p = baseline.metrics, polluted.metrics
    fields = (
        "total_return",
        "cagr",
        "volatility",
        "max_drawdown",
        "sharpe",
        "n_days",
        "start_price",
        "end_price",
    )
    for name in fields:
        bv, pv = getattr(b, name), getattr(p, name)
        if isinstance(bv, float):
            if abs(bv - pv) > tol:
                raise AssertionError(
                    f"lookahead leak on {name}: baseline={bv} polluted={pv}"
                )
        elif bv != pv:
            raise AssertionError(f"lookahead leak on {name}: baseline={bv} polluted={pv}")


def run_with_optional_pollute(
    runner: Callable[[], BacktestResult],
    pollute: Callable[[], None] | None,
) -> tuple[BacktestResult, BacktestResult]:
    """Run baseline, optionally inject future rows, re-run; return both results."""
    baseline = runner()
    if pollute is not None:
        pollute()
    polluted = runner()
    return baseline, polluted


__all__ = ["assert_metrics_unchanged", "run_with_optional_pollute", "date"]
