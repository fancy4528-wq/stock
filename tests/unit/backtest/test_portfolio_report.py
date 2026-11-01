"""Gate 4 portfolio backtest report template (§9.2)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.backtest.portfolio import (
    L2TopNBacktest,
    L2TopNConfig,
    _mdd_duration_days,
    _return_stats,
    _turnover_and_capacity,
    _worst_month,
)
from quantagent.backtest.report import (
    MatchingAssumptionStatus,
    count_unfilled_reasons,
    render_portfolio_backtest_report,
    write_portfolio_backtest_report,
)
from quantagent.execution.broker.simulated import PriceBar


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


@pytest.mark.asyncio
async def test_report_requires_matching_disclaimer_and_reject_stats() -> None:
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
    assert "limit_up_cannot_buy" in result.reject_stats
    assert "matching assumptions unverified" in result.notes

    md = render_portfolio_backtest_report(result)
    assert "## 7. 撮合假设状态" in md
    assert "撮合假设未验证" in md
    assert "未校准" in md
    assert "limit_up_cannot_buy" in md
    assert "`l2_equal_topn`" in md
    assert "未算" not in md
    assert result.worst_month is not None
    assert result.mdd_duration_days is not None
    assert result.turnover_annual is not None
    assert result.avg_volume_share is not None
    assert result.capacity_estimate is not None
    assert f"{result.avg_volume_share:+.2%}" in md


def test_count_unfilled_reasons_from_dicts() -> None:
    stats = count_unfilled_reasons(
        [
            {"reason": "t1_not_sellable"},
            {"reason": "limit_up_cannot_buy"},
            {"reason": "t1_not_sellable"},
        ]
    )
    assert stats == {"t1_not_sellable": 2, "limit_up_cannot_buy": 1}


def test_write_report_creates_parent(tmp_path) -> None:
    from quantagent.backtest.portfolio import PortfolioBacktestResult

    result = PortfolioBacktestResult(
        strategy="l2_equal_topn",
        start=date(2024, 1, 2),
        end=date(2024, 1, 10),
        top_n=5,
        initial_nav=1_000_000.0,
        end_nav=1_010_000.0,
        total_return=0.01,
        max_drawdown=-0.02,
        n_days=5,
        total_fees=100.0,
        n_unfilled=2,
        reject_stats={"volume_limit": 2},
        notes=["matching assumptions unverified"],
    )
    path = write_portfolio_backtest_report(
        result,
        tmp_path / "nested" / "report.md",
        matching=MatchingAssumptionStatus(),
    )
    text = path.read_text(encoding="utf-8")
    assert "撮合假设未验证" in text
    assert "volume_limit" in text
    assert "未算" not in text
    assert "| Sortino | — |" in text


def test_stability_and_capacity_metrics() -> None:
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 2, 1)]
    equity = [100.0, 80.0, 90.0, 110.0]
    assert _mdd_duration_days(equity) == 3
    assert _worst_month(dates, equity) == pytest.approx(-0.10)
    _cagr, _vol, _sharpe, sortino = _return_stats(dates, equity, risk_free=0.02)
    assert sortino is not None
    _cagr_up, _vol_up, _sharpe_up, sortino_up = _return_stats(
        dates, [100.0, 101.0, 102.0, 103.0], risk_free=0.0
    )
    assert sortino_up is None
    turnover, share, capacity = _turnover_and_capacity(
        dates,
        equity,
        traded_notional=40.0,
        volume_shares=[0.01, 0.03],
        max_volume_share=0.05,
    )
    assert turnover == pytest.approx((20.0 / 95.0) / ((dates[-1] - dates[0]).days / 365.25))
    assert share == pytest.approx(0.02)
    assert capacity == pytest.approx(95.0 * 0.05 / 0.02)
