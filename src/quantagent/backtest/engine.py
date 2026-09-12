"""Minimal P0 backtest: Buy&Hold equity curve + metrics (optional broker constraints)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from math import sqrt
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.core.repository.pit import PITRepository
from quantagent.decision.portfolio.lots import floor_to_lot
from quantagent.execution.broker.base import OrderRequest
from quantagent.execution.broker.simulated import PriceBar, SimulatedBroker, UnfilledRecord
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
    constraints_applied: bool = False
    total_fees: float = 0.0
    unfilled: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class BuyAndHoldConfig:
    symbol: str = "000300.SH"
    start: date = date(2015, 1, 1)
    end: date = date(2026, 9, 5)
    risk_free: float = 0.02
    initial_cash: float = 1_000_000.0
    apply_constraints: bool = True
    board: str = "main"
    # After entry, attempt a same-day sell to exercise T+1 reject path.
    probe_t1: bool = True


@dataclass
class _ConstrainedRun:
    dates: list[date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    total_fees: float = 0.0
    unfilled: list[UnfilledRecord] = field(default_factory=list)
    entry_filled: bool = False


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


def _row_bool(row: dict[str, Any], key: str, default: bool = False) -> bool:
    val = row.get(key, default)
    return bool(val) if val is not None else default


def _row_float(row: dict[str, Any], key: str, default: float) -> float:
    val = row.get(key)
    if val is None:
        return default
    return float(val)


def _price_bar_from_row(symbol: str, row: dict[str, Any]) -> PriceBar:
    close = _row_float(row, "close", 0.0)
    open_px = _row_float(row, "open", close)
    high = _row_float(row, "high", max(open_px, close))
    low = _row_float(row, "low", min(open_px, close))
    volume = _row_float(row, "volume", 1e12)
    amount = _row_float(row, "amount", 0.0)
    return PriceBar(
        symbol=symbol,
        trade_date=row["trade_date"],
        open=open_px,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
        is_suspended=_row_bool(row, "is_suspended"),
        is_limit_up=_row_bool(row, "is_limit_up"),
        is_limit_down=_row_bool(row, "is_limit_down"),
    )


def _unfilled_dicts(rows: list[UnfilledRecord]) -> list[dict[str, Any]]:
    return [
        {
            "client_order_id": u.client_order_id,
            "symbol": u.symbol,
            "side": u.side,
            "quantity": u.quantity,
            "reason": u.reason,
            "trade_date": u.trade_date.isoformat() if u.trade_date else None,
        }
        for u in rows
    ]


async def _run_with_broker(
    ordered: pl.DataFrame,
    *,
    symbol: str,
    cfg: BuyAndHoldConfig,
    market: MarketConfig,
) -> _ConstrainedRun:
    broker = SimulatedBroker(market, cash=cfg.initial_cash)
    out = _ConstrainedRun()
    lot = market.lot_size(cfg.board)
    seq = 0

    for row in ordered.iter_rows(named=True):
        td: date = row["trade_date"]
        bar = _price_bar_from_row(symbol, row)
        broker.set_bars([bar], trade_date=td)
        if out.entry_filled:
            broker.roll_day()

        if not out.entry_filled:
            cash = (await broker.get_account()).cash
            # Leave a tiny buffer for fees / slippage on the fill price.
            raw_qty = (cash * 0.995) / bar.open if bar.open > 0 else 0.0
            qty = floor_to_lot(raw_qty, lot)
            if qty > 0:
                seq += 1
                ack = await broker.place_order(
                    OrderRequest(
                        client_order_id=f"bh-buy-{symbol}-{td.isoformat()}-{seq}",
                        symbol=symbol,
                        side="buy",
                        quantity=qty,
                        order_type="market",
                    )
                )
                if ack.accepted:
                    out.entry_filled = True
                    out.total_fees += float(ack.fees or 0.0)
                    if cfg.probe_t1:
                        seq += 1
                        probe_qty = min(float(lot), float(ack.filled_qty or qty))
                        if probe_qty > 0:
                            await broker.place_order(
                                OrderRequest(
                                    client_order_id=(
                                        f"bh-t1-probe-{symbol}-{td.isoformat()}-{seq}"
                                    ),
                                    symbol=symbol,
                                    side="sell",
                                    quantity=probe_qty,
                                    order_type="market",
                                )
                            )

        nav = broker.mark_to_market()
        out.dates.append(td)
        out.equity.append(float(nav))
        out.closes.append(float(bar.close))

    out.unfilled = list(broker.unfilled)
    return out


class BuyAndHoldEngine:
    """Index / single-name Buy&Hold using PIT prices (as_of = end).

    When ``apply_constraints`` is True (default), entry goes through
    ``SimulatedBroker`` so T+1 / limit / suspend / fees apply. Equity is NAV.
    """

    def __init__(
        self,
        repo: PITRepository | None = None,
        *,
        market: MarketConfig | None = None,
    ) -> None:
        self._repo = repo or PITRepository()
        self._market = market

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
        return self._from_ordered(prices.sort("trade_date"), cfg=cfg)

    def run_from_frame(
        self,
        df: pl.DataFrame,
        *,
        symbol: str,
        risk_free: float = 0.02,
        apply_constraints: bool = False,
        initial_cash: float = 1_000_000.0,
        probe_t1: bool = True,
        board: str = "main",
    ) -> BacktestResult:
        """Unit-test helper: run metrics on an in-memory OHLCV frame."""
        cfg = BuyAndHoldConfig(
            symbol=symbol,
            risk_free=risk_free,
            apply_constraints=apply_constraints,
            initial_cash=initial_cash,
            probe_t1=probe_t1,
            board=board,
        )
        return self._from_ordered(df.sort("trade_date"), cfg=cfg)

    def _from_ordered(self, ordered: pl.DataFrame, *, cfg: BuyAndHoldConfig) -> BacktestResult:
        if ordered.is_empty():
            raise QuantAgentError(f"No prices for {cfg.symbol}")

        if not cfg.apply_constraints:
            dates = ordered["trade_date"].to_list()
            closes = [float(x) for x in ordered["close"].to_list()]
            metrics = compute_metrics(dates, closes, risk_free=cfg.risk_free)
            return BacktestResult(
                strategy="buy_and_hold",
                symbol=cfg.symbol,
                metrics=metrics,
                equity_curve=closes,
                dates=dates,
                constraints_applied=False,
            )

        market = self._market or load_market_config("CN")
        run = asyncio.run(_run_with_broker(ordered, symbol=cfg.symbol, cfg=cfg, market=market))
        if not run.entry_filled:
            raise QuantAgentError(
                f"Buy&Hold never entered {cfg.symbol}: all days blocked "
                f"(suspend/limit/fees). unfilled={_unfilled_dicts(run.unfilled)[:5]}"
            )
        # Metrics on NAV (after costs); start/end_price still report bar closes.
        metrics = compute_metrics(run.dates, run.equity, risk_free=cfg.risk_free)
        metrics = metrics.model_copy(
            update={
                "start_price": run.closes[0],
                "end_price": run.closes[-1],
            }
        )
        return BacktestResult(
            strategy="buy_and_hold",
            symbol=cfg.symbol,
            metrics=metrics,
            equity_curve=run.equity,
            dates=run.dates,
            constraints_applied=True,
            total_fees=run.total_fees,
            unfilled=_unfilled_dicts(run.unfilled),
        )
