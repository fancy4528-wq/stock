"""PIT-focused tests for ep_ttm (financial announcement filtering)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from quantagent.quant.features import (
    compute_ep_ttm_pit,
    filter_financials_as_of,
    ttm_eps_from_financials,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


def _ann(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 17, 0, tzinfo=CN_TZ)


def test_filter_financials_excludes_future_announcements() -> None:
    fin = pl.DataFrame(
        {
            "security_id": [1, 1],
            "period_end": [date(2023, 12, 31), date(2024, 3, 31)],
            "period_type": ["FY", "Q1"],
            "eps": [1.0, 0.3],
            "announced_at": [_ann(date(2024, 3, 30)), _ann(date(2024, 4, 20))],
        }
    )
    visible = filter_financials_as_of(fin, as_of=date(2024, 4, 1))
    assert visible.height == 1
    assert visible["period_type"][0] == "FY"


def test_ttm_eps_prefers_four_quarters() -> None:
    fin = pl.DataFrame(
        {
            "security_id": [1, 1, 1, 1, 1],
            "period_end": [
                date(2023, 3, 31),
                date(2023, 6, 30),
                date(2023, 9, 30),
                date(2023, 12, 31),
                date(2024, 3, 31),
            ],
            "period_type": ["Q1", "Q2", "Q3", "Q4", "Q1"],
            "eps": [0.2, 0.25, 0.3, 0.35, 0.4],
            "announced_at": [
                _ann(date(2023, 4, 20)),
                _ann(date(2023, 8, 20)),
                _ann(date(2023, 10, 20)),
                _ann(date(2024, 3, 20)),
                _ann(date(2024, 4, 20)),
            ],
        }
    )
    # Before 2024-04-20: last four quarters are Q1..Q4 2023 → 1.10
    early = ttm_eps_from_financials(fin, as_of=date(2024, 4, 1))
    assert early.height == 1
    assert abs(float(early["eps_ttm"][0]) - 1.10) < 1e-9

    # After new Q1: quarters Q2..Q4 2023 + Q1 2024 → 1.30
    late = ttm_eps_from_financials(fin, as_of=date(2024, 4, 30))
    assert abs(float(late["eps_ttm"][0]) - 1.30) < 1e-9


def test_ep_ttm_pit_does_not_use_future_filings() -> None:
    """Future-announced EPS must not leak into an earlier as_of panel."""
    prices = pl.DataFrame(
        {
            "security_id": [1, 1],
            "trade_date": [date(2024, 3, 1), date(2024, 4, 1)],
            "close": [10.0, 10.0],
        }
    )
    fin = pl.DataFrame(
        {
            "security_id": [1, 1],
            "period_end": [date(2022, 12, 31), date(2023, 12, 31)],
            "period_type": ["FY", "FY"],
            "eps": [0.5, 1.0],
            "announced_at": [_ann(date(2023, 3, 30)), _ann(date(2024, 3, 28))],
        }
    )

    # Before FY2023 announcement: only FY2022 visible → 0.5 / 10
    early = compute_ep_ttm_pit(prices, fin, as_of=date(2024, 3, 1))
    ep_early = early.filter(pl.col("trade_date") == date(2024, 3, 1))["ep_ttm"][0]
    assert abs(float(ep_early) - 0.05) < 1e-9

    # After announcement: FY2023 → 1.0 / 10
    late = compute_ep_ttm_pit(prices, fin, as_of=date(2024, 4, 1))
    ep_late = late.filter(pl.col("trade_date") == date(2024, 4, 1))["ep_ttm"][0]
    assert abs(float(ep_late) - 0.10) < 1e-9

    # Sanity: computing early as_of must ignore the 1.0 filing entirely
    leaked = ttm_eps_from_financials(fin, as_of=date(2024, 3, 1))
    assert abs(float(leaked["eps_ttm"][0]) - 0.5) < 1e-9
