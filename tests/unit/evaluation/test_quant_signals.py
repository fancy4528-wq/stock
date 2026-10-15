"""Unit tests for shadow_quant L2 equal-weight scores."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

from quantagent.evaluation.shadow.quant_signals import (
    CSI300_L2_IC_MEANS_5Y,
    l2_equal_scores_as_of,
)
from quantagent.quant.features.base import FactorInput
from quantagent.quant.features.transform import TransformConfig


def _synthetic_l2_input(n_names: int = 8, n_days: int = 80) -> FactorInput:
    rng = np.random.default_rng(42)
    start = date(2024, 1, 2)
    dates: list[date] = []
    d = start
    while len(dates) < n_days:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)

    rows: list[dict[str, object]] = []
    val_rows: list[dict[str, object]] = []
    ind_rows: list[dict[str, object]] = []
    industries = ["电子", "银行", "医药生物", "食品饮料"]
    for i in range(n_names):
        sid = i + 1
        sym = f"{600000 + i}.SH"
        ind_rows.append(
            {
                "security_id": sid,
                "symbol": sym,
                "industry_code": f"I{i % 4}",
                "industry_name": industries[i % 4],
                "level": 1,
            }
        )
        px = 10.0 + i
        for td in dates:
            ret = float(rng.normal(0.0, 0.02))
            px = max(1.0, px * (1.0 + ret))
            vol = 1_000_000.0 + i * 10_000
            amount = vol * px
            turnover = 0.01 + 0.001 * i
            rows.append(
                {
                    "security_id": sid,
                    "symbol": sym,
                    "trade_date": td,
                    "open": px,
                    "high": px * 1.01,
                    "low": px * 0.99,
                    "close": px,
                    "volume": vol,
                    "amount": amount,
                    "turnover_rate": turnover,
                    "is_suspended": False,
                    "is_limit_up": False,
                    "is_limit_down": False,
                }
            )
            val_rows.append(
                {
                    "security_id": sid,
                    "symbol": sym,
                    "trade_date": td,
                    "pe_ttm": 10.0 + i,
                    "pb": 1.0 + 0.1 * i,
                    "ps_ttm": 2.0 + 0.1 * i,
                    "market_cap": px * 1e8,
                }
            )
    return FactorInput(
        prices=pl.DataFrame(rows),
        valuations=pl.DataFrame(val_rows),
        industry=pl.DataFrame(ind_rows),
        as_of=dates[-1],
    )


def test_l2_equal_scores_as_of_returns_symbol_keys() -> None:
    data = _synthetic_l2_input()
    scores = l2_equal_scores_as_of(
        data,
        as_of=data.as_of,
        transform=TransformConfig(enabled=True),
    )
    assert len(scores) >= 3
    assert all(s.endswith(".SH") for s in scores)
    assert all(isinstance(v, float) for v in scores.values())
    # Cross-section ranks after transform → scores in [0, 1]
    assert min(scores.values()) >= 0.0
    assert max(scores.values()) <= 1.0


def test_frozen_ic_means_cover_admitted_factors() -> None:
    from quantagent.quant.models.baseline import CSI300_L1_ADMITTED_5Y

    assert set(CSI300_L2_IC_MEANS_5Y) == set(CSI300_L1_ADMITTED_5Y)
