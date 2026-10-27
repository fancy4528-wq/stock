"""L2 Top-N backtest: next-open fills, shared broker, lookahead sentinel."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.backtest.portfolio import L2TopNBacktest, L2TopNConfig
from quantagent.execution.broker.simulated import PriceBar
from quantagent.quant.training.holdout_guard import HoldoutGuard, HoldoutViolation


def _days(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    cursor = start
    while len(out) < n:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _bar(symbol: str, day: date, px: float, *, limit_up: bool = False) -> PriceBar:
    return PriceBar(
        symbol=symbol,
        trade_date=day,
        open=px,
        high=px,
        low=px,
        close=px,
        volume=1_000_000,
        is_limit_up=limit_up,
    )


def _panel(days: list[date], prices: dict[str, list[float]]) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for i, day in enumerate(days):
        for symbol, path in prices.items():
            bars.append(_bar(symbol, day, path[i]))
    return bars


@pytest.mark.asyncio
async def test_future_bars_do_not_change_history() -> None:
    days = _days(8)
    window = days[:6]
    prices = {
        "AAA": [10, 10, 10.2, 10.4, 10.1, 10.5, 500, 800],
        "BBB": [20, 20, 19.5, 19.0, 19.2, 18.8, 1, 1],
        "CCC": [15, 15, 15.1, 15.2, 15.0, 15.3, 15, 15],
    }
    scores = {
        days[0]: {"AAA": 0.9, "BBB": 0.2, "CCC": 0.1},
        days[1]: {"AAA": 0.8, "BBB": 0.4, "CCC": 0.1},
        days[2]: {"BBB": 0.9, "AAA": 0.1, "CCC": 0.2},
        days[3]: {"BBB": 0.7, "CCC": 0.6, "AAA": 0.0},
        days[4]: {"CCC": 0.5, "AAA": 0.4, "BBB": 0.1},
        days[5]: {"AAA": 0.2, "BBB": 0.2, "CCC": 0.2},
        days[6]: {"AAA": 99.0, "BBB": -99.0, "CCC": 0.0},
        days[7]: {"AAA": 99.0},
    }
    cfg = L2TopNConfig(
        start=window[0],
        end=window[-1],
        top_n=1,
        initial_cash=1_000_000,
        rebalance="daily",
    )
    engine = L2TopNBacktest()
    baseline = await engine.run(cfg, bars=_panel(window, {k: v[:6] for k, v in prices.items()}), scores=scores)
    polluted = await engine.run(cfg, bars=_panel(days, prices), scores=scores)

    assert baseline.total_fees > 0
    assert baseline.n_days == 6
    assert baseline.positions
    assert polluted.end_nav == pytest.approx(baseline.end_nav)
    assert polluted.total_return == pytest.approx(baseline.total_return)
    assert polluted.max_drawdown == pytest.approx(baseline.max_drawdown)
    assert polluted.total_fees == pytest.approx(baseline.total_fees)
    assert polluted.n_unfilled == baseline.n_unfilled
    assert polluted.positions == baseline.positions


@pytest.mark.asyncio
async def test_limit_up_buy_is_rejected() -> None:
    days = _days(3)
    bars = [
        _bar("AAA", days[0], 10),
        _bar("BBB", days[0], 10),
        _bar("AAA", days[1], 11, limit_up=True),
        _bar("BBB", days[1], 10),
        _bar("AAA", days[2], 11),
        _bar("BBB", days[2], 10),
    ]
    scores = {days[0]: {"AAA": 1.0, "BBB": 0.0}, days[1]: {"BBB": 1.0}, days[2]: {}}
    result = await L2TopNBacktest().run(
        L2TopNConfig(start=days[0], end=days[-1], top_n=1, rebalance="daily"),
        bars=bars,
        scores=scores,
    )
    assert result.n_unfilled >= 1
    assert "AAA" not in result.positions
    assert "matching assumptions unverified" in result.notes
    assert result.rebalance == "daily"


@pytest.mark.asyncio
async def test_weekly_rebalance_trades_only_on_week_boundary() -> None:
    """Signal Fri close → fill Mon open; mid-week score flips must not trade."""
    # 2024-01-02 Tue … cover two week boundaries.
    days = _days(10, start=date(2024, 1, 2))
    bars = _panel(
        days,
        {
            "AAA": [10.0] * 10,
            "BBB": [10.0] * 10,
        },
    )
    # Prefer AAA all week 1; flip hard to BBB mid-week-2 before next signal.
    scores = {d: {"AAA": 1.0, "BBB": 0.0} for d in days}
    # Wed of week 2 (days[6] if Tue start: Tue0 Wed1 Thu2 Fri3 | Mon4 Tue5 Wed6 ...)
    scores[days[6]] = {"AAA": 0.0, "BBB": 1.0}
    scores[days[7]] = {"AAA": 0.0, "BBB": 1.0}
    scores[days[8]] = {"AAA": 0.0, "BBB": 1.0}
    scores[days[9]] = {"AAA": 0.0, "BBB": 1.0}

    result = await L2TopNBacktest().run(
        L2TopNConfig(start=days[0], end=days[-1], top_n=1, rebalance="weekly"),
        bars=bars,
        scores=scores,
    )
    assert result.rebalance == "weekly"
    # Week1 Fri signal → week2 Mon fill (AAA). Week2 Fri signal → week3 Mon fill (BBB).
    assert result.n_rebalances == 2
    assert "BBB" in result.positions
    assert "AAA" not in result.positions


@pytest.mark.asyncio
async def test_holdout_end_is_refused_without_consuming_the_use(tmp_path) -> None:
    days = _days(4, start=date(2024, 1, 2))
    guard = HoldoutGuard(days[-1], tmp_path / "uses.jsonl")
    bars = _panel(days, {"AAA": [10, 10, 10, 10], "BBB": [10, 10, 10, 10]})
    scores = {day: {"AAA": 1.0, "BBB": 0.5} for day in days}
    engine = L2TopNBacktest(guard=guard)
    with pytest.raises(HoldoutViolation, match="check_access"):
        await engine.run(
            L2TopNConfig(start=days[0], end=days[-1], top_n=1, rebalance="daily"),
            bars=bars,
            scores=scores,
        )
    assert guard.uses() == []
    allowed = await engine.run(
        L2TopNConfig(start=days[0], end=days[-2], top_n=1, rebalance="daily"),
        bars=bars,
        scores=scores,
    )
    assert allowed.end == days[-2]
    assert guard.uses() == []
