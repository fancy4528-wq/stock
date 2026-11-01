"""Top-N portfolio backtest on SimulatedBroker (Gate 4).

Signal at the close of day T. Orders go out on the next session and fill at
that session's open, through the same ``rebalance_equal_weight`` shadow uses.
Default cadence is weekly (docs/08 §2.5); daily is available for smoke tests.
Bars and scores after ``end`` are ignored.
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from typing import Literal

from pydantic import BaseModel, Field

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.execution.broker.simulated import PriceBar, SimulatedBroker, UnfilledRecord
from quantagent.execution.rebalance import rebalance_equal_weight
from quantagent.quant.training.holdout_guard import HoldoutGuard
from quantagent.shared.errors import QuantAgentError

RebalanceFreq = Literal["daily", "weekly", "monthly"]


class L2TopNConfig(BaseModel):
    start: date
    end: date
    top_n: int = 15
    initial_cash: float = 1_000_000.0
    strategy: str = "l2_equal_topn"
    risk_free: float = 0.02
    # docs/08 §2.5: weekly (Mon open) or monthly; daily turnover is too high.
    rebalance: RebalanceFreq = "weekly"


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
    sortino: float | None = None
    calmar: float | None = None
    mdd_duration_days: int | None = None
    yearly_returns: dict[int, float] = Field(default_factory=dict)
    worst_month: float | None = None
    cost_to_pnl: float | None = None
    turnover_annual: float | None = None
    avg_volume_share: float | None = None
    capacity_estimate: float | None = None
    rebalance: RebalanceFreq = "weekly"
    n_rebalances: int = 0


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
        bars: list[PriceBar] | None = None,
        scores: dict[date, dict[str, float]],
        bars_by_date: dict[date, list[PriceBar]] | None = None,
    ) -> PortfolioBacktestResult:
        if cfg.end < cfg.start:
            raise QuantAgentError("backtest end is before start")
        if cfg.top_n < 1:
            raise QuantAgentError("top_n must be >= 1")
        if self.guard is not None:
            self.guard.assert_excluded(cfg.end)

        if bars_by_date is not None:
            by_date = {d: rows for d, rows in bars_by_date.items() if cfg.start <= d <= cfg.end}
        else:
            if bars is None:
                raise QuantAgentError("bars or bars_by_date is required")
            by_date = {}
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
        traded_notional = 0.0
        volume_shares: list[float] = []
        pending: list[str] | None = None
        n_rebalances = 0
        for i, session in enumerate(sessions):
            session_bars = by_date[session]
            broker.set_bars(session_bars, trade_date=session)
            broker.roll_day()
            prev = sessions[i - 1] if i > 0 else None
            if pending and _is_fill_session(session, prev, cfg.rebalance):
                acks = await rebalance_equal_weight(
                    broker,
                    self.market,
                    pending,
                    as_of=session,
                    run_id=cfg.strategy,
                )
                total_fees += sum(ack.fees for ack in acks)
                notion, shares = _fill_participation(broker, acks, session_bars)
                traded_notional += notion
                volume_shares.extend(shares)
                n_rebalances += 1
                pending = None
            equity.append(broker.mark_to_market())
            nxt = sessions[i + 1] if i + 1 < len(sessions) else None
            if _is_signal_session(session, nxt, cfg.rebalance):
                picks = _top_n(scores.get(session, {}), cfg.top_n)
                if picks:
                    pending = picks

        end_nav = equity[-1]
        positions = {p.symbol: p.quantity for p in await broker.get_positions()}
        reject_stats = _reject_stats(broker.unfilled)
        cagr, vol, sharpe, sortino = _return_stats(sessions, equity, risk_free=cfg.risk_free)
        mdd = _max_drawdown(equity)
        calmar = (cagr / abs(mdd)) if cagr is not None and mdd < 0 else None
        pnl = end_nav - cfg.initial_cash
        cost_to_pnl = (total_fees / abs(pnl)) if abs(pnl) > 1e-9 else None
        turnover, avg_share, capacity = _turnover_and_capacity(
            sessions,
            equity,
            traded_notional,
            volume_shares,
            max_volume_share=self.market.slippage.max_volume_share,
        )
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
                f"rebalance={cfg.rebalance} (n={n_rebalances})",
                "matching assumptions unverified",
            ],
            reject_stats=reject_stats,
            equity_curve=equity,
            dates=list(sessions),
            cagr=cagr,
            volatility=vol,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            mdd_duration_days=_mdd_duration_days(equity),
            yearly_returns=_yearly_returns(sessions, equity),
            worst_month=_worst_month(sessions, equity),
            cost_to_pnl=cost_to_pnl,
            turnover_annual=turnover,
            avg_volume_share=avg_share,
            capacity_estimate=capacity,
            rebalance=cfg.rebalance,
            n_rebalances=n_rebalances,
        )


def _period_key(day: date, freq: RebalanceFreq) -> tuple[int, int]:
    if freq == "monthly":
        return day.year, day.month
    iso = day.isocalendar()
    return int(iso[0]), int(iso[1])


def _is_fill_session(session: date, prev: date | None, freq: RebalanceFreq) -> bool:
    """True on the first session of a new period (or every day if daily)."""
    if freq == "daily":
        return True
    if prev is None:
        return False
    return _period_key(session, freq) != _period_key(prev, freq)


def _is_signal_session(session: date, nxt: date | None, freq: RebalanceFreq) -> bool:
    """True on the last session of a period (or every day if daily)."""
    if freq == "daily":
        return True
    if nxt is None:
        return True
    return _period_key(session, freq) != _period_key(nxt, freq)


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


def _daily_returns(equity: list[float]) -> list[float]:
    rets: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev and prev > 0:
            rets.append(equity[i] / prev - 1.0)
    return rets


def _return_stats(
    dates: list[date],
    equity: list[float],
    *,
    risk_free: float,
) -> tuple[float | None, float | None, float | None, float | None]:
    if len(dates) < 2 or len(equity) < 2:
        return None, None, None, None
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    cagr = (equity[-1] / equity[0]) ** (1.0 / years) - 1.0
    rets = _daily_returns(equity)
    if not rets:
        return cagr, 0.0, 0.0, None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    vol = sqrt(var) * sqrt(252.0)
    excess = mean * 252.0 - risk_free
    sharpe = excess / vol if vol > 1e-12 else 0.0
    return cagr, vol, sharpe, _sortino(rets, risk_free=risk_free, excess=excess)


def _sortino(rets: list[float], *, risk_free: float, excess: float) -> float | None:
    """Excess return over downside deviation below the daily risk-free rate."""
    daily_rf = risk_free / 252.0
    downside = [min(r - daily_rf, 0.0) for r in rets]
    down_var = sum(d * d for d in downside) / len(rets)
    down_dev = sqrt(down_var) * sqrt(252.0)
    if down_dev <= 1e-12:
        return None
    return excess / down_dev


def _mdd_duration_days(equity: list[float]) -> int:
    """Trading days from the peak of the worst drawdown until recovery or end."""
    if not equity:
        return 0
    peak = equity[0]
    peak_i = 0
    worst = 0.0
    worst_peak_i = 0
    trough_i = 0
    for i, nav in enumerate(equity):
        if nav >= peak:
            peak = nav
            peak_i = i
        if peak > 0:
            dd = nav / peak - 1.0
            if dd < worst:
                worst = dd
                worst_peak_i = peak_i
                trough_i = i
    if worst >= 0:
        return 0
    peak_nav = equity[worst_peak_i]
    end_i = len(equity) - 1
    for j in range(trough_i, len(equity)):
        if equity[j] >= peak_nav - 1e-9:
            end_i = j
            break
    return end_i - worst_peak_i


def _worst_month(dates: list[date], equity: list[float]) -> float | None:
    """Minimum month-end return. The first month is measured from the first NAV."""
    monthly = _monthly_returns(dates, equity)
    if not monthly:
        return None
    return min(monthly)


def _monthly_returns(dates: list[date], equity: list[float]) -> list[float]:
    if len(dates) != len(equity) or not dates:
        return []
    last: dict[tuple[int, int], float] = {}
    first: dict[tuple[int, int], float] = {}
    for day, nav in zip(dates, equity, strict=True):
        key = (day.year, day.month)
        first.setdefault(key, nav)
        last[key] = nav
    rets: list[float] = []
    prev: tuple[int, int] | None = None
    for key in sorted(last):
        base = first[key] if prev is None else last[prev]
        if base and base > 0:
            rets.append(last[key] / base - 1.0)
        prev = key
    return rets


def _fill_participation(
    broker: SimulatedBroker,
    acks: list[object],
    bars: list[PriceBar],
) -> tuple[float, list[float]]:
    """Traded notional and each fill's share of that session's volume."""
    by_symbol = {bar.symbol: bar for bar in bars}
    notional = 0.0
    shares: list[float] = []
    for ack in acks:
        filled = float(getattr(ack, "filled_qty", 0.0) or 0.0)
        price = getattr(ack, "avg_price", None)
        if filled <= 0 or price is None:
            continue
        notional += filled * float(price)
        order_id = getattr(ack, "client_order_id", None)
        state = broker._orders.get(order_id) if order_id else None  # noqa: SLF001
        if state is None:
            continue
        bar = by_symbol.get(state.symbol)
        if bar is not None and bar.volume > 0:
            shares.append(filled / float(bar.volume))
    return notional, shares


def _turnover_and_capacity(
    dates: list[date],
    equity: list[float],
    traded_notional: float,
    volume_shares: list[float],
    *,
    max_volume_share: float,
) -> tuple[float | None, float | None, float | None]:
    """One-way annual turnover, mean fill participation, and capacity.

    Capacity is the average NAV scaled until mean participation equals
    ``max_volume_share`` (docs/08 §4.1 / §9.2).
    """
    if len(dates) < 2 or not equity:
        return None, None, None
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    avg_nav = sum(equity) / len(equity)
    turnover = None
    if avg_nav > 0 and traded_notional > 0:
        turnover = (traded_notional / 2.0) / avg_nav / years
    avg_share = None
    capacity = None
    if volume_shares:
        avg_share = sum(volume_shares) / len(volume_shares)
        if avg_share > 1e-12 and avg_nav > 0 and max_volume_share > 0:
            capacity = avg_nav * (max_volume_share / avg_share)
    return turnover, avg_share, capacity


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
