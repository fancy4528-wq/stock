"""Unit tests for calendar validation rules."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.data.validators.calendar import CALENDAR_RULES


def _ok_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "market": ["CN", "CN", "CN"],
            "trade_date": [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)],
            "is_open": [True, True, False],
            "prev_trade_date": [None, date(2026, 9, 1), date(2026, 9, 2)],
            "next_trade_date": [date(2026, 9, 2), None, None],
            "note": [None, None, None],
            "source": ["akshare", "akshare", "akshare"],
        }
    )


def test_calendar_rules_pass() -> None:
    df = _ok_frame()
    results = {r.code: r for r in (rule(df) for rule in CALENDAR_RULES)}
    assert results["CAL_001"].status == "pass"
    assert results["CAL_002"].status == "pass"
    assert results["CAL_003"].status == "pass"


def test_calendar_rules_fail_no_open() -> None:
    df = _ok_frame().with_columns(pl.lit(False).alias("is_open"))
    results = {r.code: r for r in (rule(df) for rule in CALENDAR_RULES)}
    assert results["CAL_002"].status == "fail"
