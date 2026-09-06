"""Unit tests for live report builders (no DB)."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from quantagent.reporting.live import (
    add_forward_returns,
    bars_from_day_prices,
    build_factor_metrics,
    build_factor_ranks,
    build_market_overview,
    scores_as_of,
    select_factor_codes,
)


def _panel(n_syms: int = 10, n_days: int = 40) -> pl.DataFrame:
    start = date(2026, 7, 1)
    rows: list[dict[str, object]] = []
    for i in range(n_syms):
        sym = f"{600000 + i}.SH"
        px = 10.0 + i
        for d in range(n_days):
            td = start + timedelta(days=d)
            # skip weekends roughly
            if td.weekday() >= 5:
                continue
            ret = ((i * 3 + d) % 7 - 3) / 1000.0
            close = px * (1.0 + ret)
            px = close
            rows.append(
                {
                    "symbol": sym,
                    "security_id": i + 1,
                    "trade_date": td,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "prev_close": close / (1.0 + ret) if ret != -1 else close,
                    "volume": 1_000_000 + i * 1000,
                    "amount": close * (1_000_000 + i * 1000),
                    "turnover_rate": 0.01 + i * 0.001,
                    "is_limit_up": False,
                    "is_limit_down": False,
                    "is_suspended": False,
                }
            )
    return pl.DataFrame(rows)


def test_bars_from_day_prices() -> None:
    panel = _panel()
    as_of = panel["trade_date"].max()
    day = panel.filter(pl.col("trade_date") == as_of)
    bars = bars_from_day_prices(day)
    assert len(bars) == day.height
    assert bars[0].symbol.endswith(".SH")


def test_scores_and_ranks() -> None:
    panel = _panel()
    as_of = panel["trade_date"].max()
    assert isinstance(as_of, date)
    # fake factor = close
    fp = panel.with_columns(pl.col("close").alias("mom_20d"))
    scores = scores_as_of(fp, as_of=as_of, factor="mom_20d")
    assert len(scores) == 10
    ranks = build_factor_ranks(
        fp, as_of=as_of, factor="mom_20d", names={s: s for s in scores}, top_n=3
    )
    assert len(ranks) == 3
    assert ranks[0].rank == 1


def test_factor_metrics_and_overview() -> None:
    panel = _panel()
    as_of = panel["trade_date"].max()
    assert isinstance(as_of, date)
    fp = add_forward_returns(panel.with_columns(pl.col("close").alias("mom_20d")))
    metrics = build_factor_metrics(fp, as_of=as_of, factor_codes=["mom_20d"])
    assert metrics and metrics[0].factor == "mom_20d"

    day = panel.filter(pl.col("trade_date") == as_of)
    idx = panel.filter(pl.col("symbol") == "600000.SH")
    overview = build_market_overview(
        as_of=as_of,
        index_panel=idx,
        universe_day=day,
        universe_hist=panel,
        index_symbol="600000.SH",
    )
    assert overview.n_up + overview.n_down + overview.n_flat == day.height
    assert overview.index_close > 0


def test_select_factor_codes() -> None:
    codes = select_factor_codes(_panel())
    assert "mom_20d" in codes
    assert "ep_ttm" not in codes
    assert "turnover_20d" in codes
