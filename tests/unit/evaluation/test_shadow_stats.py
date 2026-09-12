"""Shadow unfilled order statistics."""

from __future__ import annotations

from datetime import date

from quantagent.evaluation.shadow.stats import summarize_unfilled
from quantagent.evaluation.shadow.types import ShadowDayRecord


def test_summarize_unfilled_counts_reasons() -> None:
    limit_up = "limit_up_cannot_buy"
    insufficient = "insufficient_sellable"
    records = [
        ShadowDayRecord(
            portfolio="shadow_factor",
            as_of=date(2026, 9, 1),
            run_id="r1",
            strategy_version="v1",
            nav=1_000_000.0,
            cash=100_000.0,
            ret_1d=0.0,
            ret_cum=0.0,
            max_drawdown=0.0,
            n_positions=10,
            unfilled=[
                {"symbol": "600003.SH", "side": "buy", "quantity": 100.0, "reason": limit_up},
                {"symbol": "600004.SH", "side": "buy", "quantity": 100.0, "reason": limit_up},
                {"symbol": "600005.SH", "side": "sell", "quantity": 50.0, "reason": insufficient},
            ],
        ),
        ShadowDayRecord(
            portfolio="shadow_baseline",
            as_of=date(2026, 9, 1),
            run_id="r1",
            strategy_version="v1",
            nav=1_000_000.0,
            cash=100_000.0,
            ret_1d=0.0,
            ret_cum=0.0,
            max_drawdown=0.0,
            n_positions=50,
            unfilled=[
                {"symbol": "600003.SH", "side": "buy", "quantity": 100.0, "reason": limit_up},
            ],
        ),
    ]
    stats = summarize_unfilled(records)
    assert stats == {
        "limit_up_cannot_buy": 3,
        "insufficient_sellable": 1,
    }
