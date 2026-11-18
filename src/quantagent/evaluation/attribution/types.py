"""Backtest attribution results (docs/08 §7)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReturnDecomposition(BaseModel):
    """Total return split into market / sector / stock / timing / cost.

    Components are arithmetic daily sums; ``residual`` absorbs compounding and
    model error so ``market + sector + stock + timing + cost + residual``
    equals ``total_return``.
    """

    total_return: float
    market: float = 0.0
    sector_allocation: float = 0.0
    stock_selection: float = 0.0
    timing: float = 0.0
    cost: float = 0.0
    residual: float = 0.0
    beta: float | None = None
    benchmark_return: float | None = None
    n_days: int = 0
    note: str = ""


class SignalContribution(BaseModel):
    """One single-signal (or control) portfolio vs fused / baseline."""

    signal: str
    portfolio_return: float
    vs_baseline: float | None = None
    vs_fused: float | None = None
    note: str = ""


class AttributionResult(BaseModel):
    """docs/08 §7.1 return decomp + §7.2 signal contribution."""

    returns: ReturnDecomposition
    signals: list[SignalContribution] = Field(default_factory=list)
    signal_note: str = ""
