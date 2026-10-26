"""Top-N portfolio backtest on SimulatedBroker (Gate 4).

Signal at the close of day T. Orders go out on the next session and fill at
that session's open, through the same ``rebalance_equal_weight`` shadow uses.
Bars and scores after ``end`` are ignored.
"""

from __future__ import annotations

from datetime import date
from math import sqrt

from pydantic import BaseModel, Field

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.execution.broker.simulated import PriceBar, SimulatedBroker, UnfilledRecord
from quantagent.execution.rebalance import rebalance_equal_weight
from quantagent.quant.training.holdout_guard import HoldoutGuard
from quantagent.shared.errors import QuantAgentError


class L2TopNConfig(BaseModel):
    start: date
    end: date
    top_n: int = 15
    initial_cash: float = 1_000_000.0
    strategy: str = "l2_equal_topn"
    risk_free: float = 0.02


class PortfolioBacktestResult(BaseModel):
    strategy: str
    start: date
    end: date
    top_n: int
    initial_nav: float
    end_nav: float
    total_return: float
    max_drawdown: float
    n_days: int
    total_fees: float
    n_unfilled: int
    positions: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    reject_stats: dict[str, int] = Field(default_factory=dict)
    equity_curve: list[float] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    cagr: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    calmar: float | None = None
    yearly_returns: dict[int, float] = Field(default_factory=dict)
    cost_to_pnl: float | None = None


class L2TopNBacktest:
    """Equal-weight Top-N booked with the shared simulated broker."""

    def __init__(
        self,
        market: MarketConfig | None = None,
        *,
        guard: HoldoutGuard | None = None,
    ) -> None:
        self.market = market or load_market_config("CN")
        self.guard = guard

    async def run(
        self,
        cfg: L2TopNConfig,
        *,
        bars: list[PriceBar],
        scores: dict[date, dict[str, float]],
    ) -> PortfolioBacktestResult:
        if cfg.end < cfg.start:
            raise QuantAgentError("backtest end is before start")
        if cfg.top_n < 1:
            raise QuantAgentError("top_n must be >= 1")
        if self.guard is not None:
            self.guard.assert_excluded(cfg.end)

        by_date: dict[date, list[PriceBar]] = {}
        for bar in bars:
            if bar.trade_date < cfg.start or bar.trade_date > cfg.end:
                continue
            by_date.setdefault(bar.trade_date, []).append(bar)
        sessions = sorted(by_date)
        if len(sessions) < 2:
            raise QuantAgentError(
                "portfolio backtest needs at least two sessions inside the window"
            )

        broker = SimulatedBroker(self.market, cash=cfg.initial_cash)
        equity: list[float] = []
        total_fees = 0.0
        pending: list[str] | None = None
        for session in sessions:
            broker.set_bars(by_date[session], trade_date=session)
            broker.roll_day()
            if pending:
                acks = await rebalance_equal_weight(
                    broker,
                    self.market,
                    pending,
                    as_of=session,
                    run_id=cfg.strategy,
                )
                total_fees += sum(ack.fees for ack in acks)
            equity.append(broker.mark_to_market())
            pending = _top_n(scores.get(session, {}), cfg.top_n)

        end_nav = equity[-1]
        positions = {p.symbol: p.quantity for p in await broker.get_positions()}
        reject_stats = _reject_stats(broker.unfilled)
        cagr, vol, sharpe = _return_stats(sessions, equity, risk_free=cfg.risk_free)
        mdd = _max_drawdown(equity)
        calmar = (cagr / abs(mdd)) if cagr is not None and mdd < 0 else None
        pnl = end_nav - cfg.initial_cash
        cost_to_pnl = (total_fees / abs(pnl)) if abs(pnl) > 1e-9 else None
        return PortfolioBacktestResult(
            strategy=cfg.strategy,
            start=cfg.start,
            end=cfg.end,
            top_n=cfg.top_n,
            initial_nav=cfg.initial_cash,
            end_nav=end_nav,
            total_return=end_nav / cfg.initial_cash - 1.0,
            max_drawdown=mdd,
            n_days=len(equity),
            total_fees=total_fees,
            n_unfilled=len(broker.unfilled),
            positions=positions,
            notes=[
                "signal at close, fill at next open",
                "matching assumptions unverified",
            ],
            reject_stats=reject_stats,
            equity_curve=equity,
            dates=list(sessions),
            cagr=cagr,
            volatility=vol,
            sharpe=sharpe,
            calmar=calmar,
            yearly_returns=_yearly_returns(sessions, equity),
            cost_to_pnl=cost_to_pnl,
        )


def _reject_stats(unfilled: list[UnfilledRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in unfilled:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _top_n(scores: dict[str, float], top_n: int) -> list[str]:
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [symbol for symbol, _ in ranked[:top_n]]


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    worst = 0.0
    for nav in equity:
        peak = max(peak, nav)
        if peak > 0:
            worst = min(worst, nav / peak - 1.0)
    return worst


def _return_stats(
    dates: list[date],
    equity: list[float],
    *,
    risk_free: float,
) -> tuple[float | None, float | None, float | None]:
    if len(dates) < 2 or len(equity) < 2:
        return None, None, None
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    cagr = (equity[-1] / equity[0]) ** (1.0 / years) - 1.0
    rets: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev and prev > 0:
            rets.append(equity[i] / prev - 1.0)
    if not rets:
        return cagr, 0.0, 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    vol = sqrt(var) * sqrt(252.0)
    excess = mean * 252.0 - risk_free
    sharpe = excess / vol if vol > 1e-12 else 0.0
    return cagr, vol, sharpe


def _yearly_returns(dates: list[date], equity: list[float]) -> dict[int, float]:
    if len(dates) != len(equity) or not dates:
        return {}
    by_year: dict[int, tuple[float, float]] = {}
    for d, nav in zip(dates, equity, strict=True):
        first, last = by_year.get(d.year, (nav, nav))
        by_year[d.year] = (first, nav)
    out: dict[int, float] = {}
    for year, (first, last) in sorted(by_year.items()):
        if first and first > 0:
            out[year] = last / first - 1.0
    return out
