"""Backtest attribution: return decomp + signal contribution (docs/08 §7)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.backtest.portfolio import L2TopNBacktest, L2TopNConfig
from quantagent.backtest.report import render_portfolio_backtest_report
from quantagent.evaluation.attribution import (
    AttributionResult,
    ReturnDecomposition,
    attribute_by_signal,
    attribute_portfolio,
    daily_stock_returns_from_bars,
    decompose_returns,
    render_attribution_section,
    signal_returns_from_shadows,
)
from quantagent.evaluation.shadow.types import ShadowDayRecord
from quantagent.execution.broker.simulated import PriceBar


def _days(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    cursor = start
    while len(out) < n:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _bar(symbol: str, day: date, px: float) -> PriceBar:
    return PriceBar(
        symbol=symbol,
        trade_date=day,
        open=px,
        high=px,
        low=px,
        close=px,
        volume=1_000_000,
    )


def test_decompose_ties_out_with_residual() -> None:
    days = _days(5)
    # Fully invested in A (sector X); B is the other sector in the basket.
    equity = [100.0, 101.0, 103.0, 102.0, 104.0]
    weights = [{"A": 1.0}] * 5
    cash = [0.0] * 5
    fees = [0.0, 0.1, 0.0, 0.0, 0.2]
    bench = [0.01, 0.01, -0.005, 0.01]
    stock_rets = {
        days[1]: {"A": 0.02, "B": 0.00},
        days[2]: {"A": 0.02, "B": 0.01},
        days[3]: {"A": -0.01, "B": 0.00},
        days[4]: {"A": 0.02, "B": 0.01},
    }
    industry = {"A": "X", "B": "Y"}
    decomp = decompose_returns(
        dates=days,
        equity=equity,
        weights_history=weights,
        cash_weights=cash,
        daily_fees=fees,
        benchmark_returns=bench,
        stock_returns=stock_rets,
        industry_map=industry,
        initial_nav=100.0,
    )
    parts = (
        decomp.market
        + decomp.sector_allocation
        + decomp.stock_selection
        + decomp.timing
        + decomp.cost
        + decomp.residual
    )
    assert decomp.total_return == pytest.approx(0.04)
    assert parts == pytest.approx(decomp.total_return, abs=1e-12)
    assert decomp.cost < 0
    assert decomp.beta is not None
    assert decomp.n_days == 5


def test_timing_negative_when_holding_cash_in_up_market() -> None:
    days = _days(3)
    equity = [100.0, 100.5, 101.0]  # mild gain while half in cash
    weights = [{"A": 0.5}, {"A": 0.5}, {"A": 0.5}]
    cash = [0.5, 0.5, 0.5]
    fees = [0.0, 0.0, 0.0]
    bench = [0.02, 0.02]  # strong up market
    decomp = decompose_returns(
        dates=days,
        equity=equity,
        weights_history=weights,
        cash_weights=cash,
        daily_fees=fees,
        benchmark_returns=bench,
    )
    assert decomp.timing < 0


def test_stock_returns_from_bars() -> None:
    days = _days(3)
    bars = [
        _bar("A", days[0], 10),
        _bar("A", days[1], 11),
        _bar("A", days[2], 10.45),
        _bar("B", days[0], 20),
        _bar("B", days[1], 20),
        _bar("B", days[2], 22),
    ]
    rets = daily_stock_returns_from_bars(bars)
    assert rets[days[1]]["A"] == pytest.approx(0.1)
    assert rets[days[2]]["B"] == pytest.approx(0.1)


def test_attribute_by_signal_deltas() -> None:
    rows, note = attribute_by_signal(
        fused_return=0.10,
        baseline_return=0.05,
        signal_returns={"quant": 0.08, "news": 0.02},
    )
    assert len(rows) == 2
    by_name = {r.signal: r for r in rows}
    assert by_name["quant"].vs_baseline == pytest.approx(0.03)
    assert by_name["quant"].vs_fused == pytest.approx(-0.02)
    assert by_name["news"].vs_baseline == pytest.approx(-0.03)
    assert "不改 Fusion" in note


def test_signal_returns_from_shadows() -> None:
    days = _days(4)
    records = [
        ShadowDayRecord(
            portfolio="shadow_quant",
            as_of=days[0],
            run_id="r",
            strategy_version="v",
            nav=1_000_000,
            cash=0,
            ret_1d=0.0,
            ret_cum=0.0,
            max_drawdown=0.0,
            n_positions=1,
        ),
        ShadowDayRecord(
            portfolio="shadow_quant",
            as_of=days[3],
            run_id="r",
            strategy_version="v",
            nav=1_100_000,
            cash=0,
            ret_1d=0.0,
            ret_cum=0.10,
            max_drawdown=0.0,
            n_positions=1,
        ),
        ShadowDayRecord(
            portfolio="shadow_baseline",
            as_of=days[0],
            run_id="r",
            strategy_version="v",
            nav=1_000_000,
            cash=0,
            ret_1d=0.0,
            ret_cum=0.0,
            max_drawdown=0.0,
            n_positions=1,
        ),
        ShadowDayRecord(
            portfolio="shadow_baseline",
            as_of=days[3],
            run_id="r",
            strategy_version="v",
            nav=1_050_000,
            cash=0,
            ret_1d=0.0,
            ret_cum=0.05,
            max_drawdown=0.0,
            n_positions=1,
        ),
    ]
    rets = signal_returns_from_shadows(records, start=days[0], end=days[3])
    assert rets["quant"] == pytest.approx(0.10)
    assert rets["baseline"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_portfolio_backtest_records_weights_and_report_section() -> None:
    days = _days(4)
    bars = []
    for d in days:
        bars.extend([_bar("AAA", d, 10.0 + days.index(d)), _bar("BBB", d, 10.0)])
    scores = {d: {"AAA": 1.0, "BBB": 0.0} for d in days}
    result = await L2TopNBacktest().run(
        L2TopNConfig(
            start=days[0],
            end=days[-1],
            top_n=1,
            rebalance="daily",
            max_turnover=1.0,
        ),
        bars=bars,
        scores=scores,
    )
    assert len(result.weights_history) == result.n_days
    assert len(result.cash_weights) == result.n_days
    assert len(result.daily_fees) == result.n_days
    assert sum(result.daily_fees) == pytest.approx(result.total_fees)

    industry = {"AAA": "tech", "BBB": "fin"}
    attrib = attribute_portfolio(
        result,
        bars=bars,
        industry_map=industry,
        benchmark_returns=[0.0] * (result.n_days - 1),
        signal_returns={"quant": 0.01, "news": -0.01},
        baseline_return=0.0,
    )
    tied = (
        attrib.returns.market
        + attrib.returns.sector_allocation
        + attrib.returns.stock_selection
        + attrib.returns.timing
        + attrib.returns.cost
        + attrib.returns.residual
    )
    assert tied == pytest.approx(attrib.returns.total_return, abs=1e-9)
    assert len(attrib.signals) == 2

    md = render_portfolio_backtest_report(result, attribution=attrib)
    assert "## 8. 归因分析" in md
    assert "收益分解" in md
    assert "信号贡献" in md
    assert "`quant`" in md
    assert "## 7. 撮合假设状态" in md


def test_render_attribution_section_empty_signals() -> None:
    result = AttributionResult(
        returns=ReturnDecomposition(total_return=0.1, market=0.08, residual=0.02),
        signal_note="无单信号组合收益",
    )
    md = render_attribution_section(result)
    assert "## 8. 归因分析" in md
    assert "无单信号" in md
