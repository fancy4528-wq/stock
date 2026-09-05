"""Unit tests that do not require Postgres."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.core.assertions import assert_no_lookahead
from quantagent.core.repository.pit import PITRepository
from quantagent.shared.errors import LookaheadError


def test_as_of_is_keyword_only() -> None:
    repo = PITRepository.__new__(PITRepository)
    with pytest.raises(TypeError):
        repo.get_financials(["600519.SH"], date(2020, 1, 1))  # type: ignore[misc]
    with pytest.raises(TypeError):
        repo.get_prices(["600519.SH"], date(2020, 1, 1), start=date(2020, 1, 1))  # type: ignore[misc]
    with pytest.raises(TypeError):
        repo.get_industry(["600519.SH"], date(2020, 1, 1))  # type: ignore[misc]
    with pytest.raises(TypeError):
        repo.get_universe(date(2020, 1, 1), name="mvp")  # type: ignore[misc]


def test_assert_no_lookahead_passes() -> None:
    df = pl.DataFrame({"announced_at": [datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))]})
    assert_no_lookahead(df, date(2020, 6, 1), "announced_at")


def test_assert_no_lookahead_raises() -> None:
    df = pl.DataFrame({"announced_at": [datetime(2021, 1, 1, tzinfo=ZoneInfo("UTC"))]})
    with pytest.raises(LookaheadError):
        assert_no_lookahead(df, date(2020, 6, 1), "announced_at")
