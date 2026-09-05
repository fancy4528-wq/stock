"""Minimal P0 backtest: Buy&Hold equity curve + metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt

import polars as pl
from pydantic import BaseModel, Field

from quantagent.core.repository.pit import PITRepository
from quantagent.shared.errors import QuantAgentError


class BacktestMetrics(BaseModel):
    total_return: float
    cagr: float
    volatility: float
    max_drawdown: float
    sharpe: float
    n_days: int
    start: date
    end: date
    start_price: float
    end_price: float


class BacktestResult(BaseModel):
    strategy: str
    symbol: str
    metrics: BacktestMetrics
    equity_curve: list[float] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)


@dataclass(frozen=True)
class BuyAndHoldConfig:
    symbol: str = "000300.SH"
    start: date = date(2015, 1, 1)
    end: date = date(2026, 9, 5)
    risk_free: float = 0.02


def compute_metrics(
    dates: list[date],
    closes: list[float],
    *,
    risk_free: float = 0.02,
) -> BacktestMetrics:
    if len(dates) < 2 or len(closes) < 2:
        raise QuantAgentError("Need at least 2 price points for Buy&Hold metrics")
    start_px, end_px = float(closes[0]), float(closes[-1])
    total_return = end_px / start_px - 1.0
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    cagr = (end_px / start_px) ** (1.0 / years) - 1.0

    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev and prev > 0:
            rets.append(closes[i] / prev - 1.0)
    if rets:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
        vol = sqrt(var) * sqrt(252.0)
        excess = mean * 252.0 - risk_free
        sharpe = excess / vol if vol > 1e-12 else 0.0
    else:
        vol = 0.0
        sharpe = 0.0

    peak = closes[0]
    max_dd = 0.0
    for px in closes:
        peak = max(peak, px)
        dd = px / peak - 1.0
        max_dd = min(max_dd, dd)

    return BacktestMetrics(
        total_return=total_return,
        cagr=cagr,
        volatility=vol,
        max_drawdown=max_dd,
        sharpe=sharpe,
        n_days=len(closes),
        start=dates[0],
        end=dates[-1],
        start_price=start_px,
        end_price=end_px,
    )


class BuyAndHoldEngine:
    """Index / single-name Buy&Hold using PIT prices (as_of = end)."""

    def __init__(self, repo: PITRepository | None = None) -> None:
        self._repo = repo or PITRepository()

    def run(self, cfg: BuyAndHoldConfig) -> BacktestResult:
        # Index series usually has no adjust_factor rows → COALESCE factor=1.
        prices = self._repo.get_prices(
            [cfg.symbol],
            as_of=cfg.end,
            start=cfg.start,
            end=cfg.end,
            adjust="qfq",
        )
        if prices.is_empty():
            raise QuantAgentError(
                f"No prices for {cfg.symbol} in [{cfg.start}, {cfg.end}] as_of={cfg.end}"
            )

        ordered = prices.sort("trade_date")
        dates = ordered["trade_date"].to_list()
        closes = [float(x) for x in ordered["close"].to_list()]
        metrics = compute_metrics(dates, closes, risk_free=cfg.risk_free)
        return BacktestResult(
            strategy="buy_and_hold",
            symbol=cfg.symbol,
            metrics=metrics,
            equity_curve=closes,
            dates=dates,
        )

    def run_from_frame(
        self, df: pl.DataFrame, *, symbol: str, risk_free: float = 0.02
    ) -> BacktestResult:
        """Unit-test helper: run metrics on an in-memory OHLCV frame."""
        ordered = df.sort("trade_date")
        dates = ordered["trade_date"].to_list()
        closes = [float(x) for x in ordered["close"].to_list()]
        metrics = compute_metrics(dates, closes, risk_free=risk_free)
        return BacktestResult(
            strategy="buy_and_hold",
            symbol=symbol,
            metrics=metrics,
            equity_curve=closes,
            dates=dates,
        )
