"""Calendar dual-source comparison helpers (edge-case D2)."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.data.normalizers.calendar import open_dates
from quantagent.data.validators.report import RuleResult


def compare_calendar_open_days(
    primary: pl.DataFrame,
    secondary: pl.DataFrame,
    *,
    window_start: date | None = None,
) -> RuleResult:
    """Compare open-day sets; WARN when sources disagree."""
    a_df = primary
    b_df = secondary
    if window_start is not None:
        a_df = a_df.filter(pl.col("trade_date") >= window_start)
        b_df = b_df.filter(pl.col("trade_date") >= window_start)
    a = open_dates(a_df)
    b = open_dates(b_df)
    only_a = sorted(a - b)
    only_b = sorted(b - a)
    failed = bool(only_a or only_b)
    return RuleResult(
        code="CAL_DUAL",
        level="WARN",
        status="warn" if failed else "pass",
        detail=(
            f"primary_only={len(only_a)} secondary_only={len(only_b)}"
            if failed
            else f"ok open_days={len(a)}"
        ),
        affected_count=len(only_a) + len(only_b),
        affected_keys=[d.isoformat() for d in (only_a + only_b)[:10]],
        expected={"open_days_equal": True},
        actual={
            "primary_only": [d.isoformat() for d in only_a[:5]],
            "secondary_only": [d.isoformat() for d in only_b[:5]],
        },
    )
