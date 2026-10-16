"""Top-N portfolio backtest on SimulatedBroker (Gate 4).

Signal at the close of day T. Orders go out on the next session and fill at
that session's open, through the same ``rebalance_equal_weight`` shadow uses.
Bars and scores after ``end`` are ignored.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.execution.broker.simulated import PriceBar, SimulatedBroker
from quantagent.execution.rebalance import rebalance_equal_weight
from quantagent.quant.training.holdout_guard import HoldoutGuard
from quantagent.shared.errors import QuantAgentError


class L2TopNConfig(BaseModel):
    start: date
    end: date
    top_n: int = 15
    initial_cash: float = 1_000_000.0
    strategy: str = "l2_equal_topn"


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
            raise QuantAgentError("portfolio backtest needs at least two sessions inside the window")

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
        return PortfolioBacktestResult(
            strategy=cfg.strategy,
            start=cfg.start,
            end=cfg.end,
            top_n=cfg.top_n,
            initial_nav=cfg.initial_cash,
            end_nav=end_nav,
            total_return=end_nav / cfg.initial_cash - 1.0,
            max_drawdown=_max_drawdown(equity),
            n_days=len(equity),
            total_fees=total_fees,
            n_unfilled=len(broker.unfilled),
            positions=positions,
            notes=[
                "signal at close, fill at next open",
                "matching assumptions unverified",
            ],
        )


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
