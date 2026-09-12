"""Unit tests for adjust-factor loader revision logic."""

from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import polars as pl

from quantagent.data.loaders.adjust import AdjustLoader

CN_TZ = ZoneInfo("Asia/Shanghai")


def _frame(
    *,
    factor_qfq: float = 1.0,
    factor_hfq: float = 1.0,
    trade_date: date = date(2026, 6, 15),
) -> pl.DataFrame:
    announced = datetime.combine(trade_date, time(15, 0), tzinfo=CN_TZ)
    return pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "trade_date": [trade_date],
            "factor_qfq": [factor_qfq],
            "factor_hfq": [factor_hfq],
            "announced_at": [announced],
            "source": ["baostock"],
        }
    )


def test_insert_factors_bumps_revision_on_change() -> None:
    loader = AdjustLoader(engine=MagicMock())
    conn = MagicMock()
    id_map = {"600519.SH": 1}

    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [
        {"revision": 1, "factor_qfq": 1.0, "factor_hfq": 1.0, "announced_at": "x"}
    ]
    insert_result = MagicMock()
    conn.execute.side_effect = [select_result, insert_result]
    n = loader._insert_factors(conn, _frame(factor_qfq=1.1), id_map=id_map, source="baostock")
    assert n == 1
    insert_call = conn.execute.call_args_list[1]
    params = insert_call[0][1]
    assert params["revision"] == 2


def test_insert_factors_skips_unchanged() -> None:
    loader = AdjustLoader(engine=MagicMock())
    conn = MagicMock()
    id_map = {"600519.SH": 1}
    announced = datetime.combine(date(2026, 6, 15), time(15, 0), tzinfo=CN_TZ)
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [
        {
            "revision": 1,
            "factor_qfq": 1.0,
            "factor_hfq": 1.0,
            "announced_at": announced,
        }
    ]
    conn.execute.return_value = select_result
    n = loader._insert_factors(conn, _frame(), id_map=id_map, source="baostock")
    assert n == 0
    assert conn.execute.call_count == 1


def test_insert_factors_first_revision() -> None:
    loader = AdjustLoader(engine=MagicMock())
    conn = MagicMock()
    id_map = {"600519.SH": 1}
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = []
    insert_result = MagicMock()
    conn.execute.side_effect = [select_result, insert_result]
    n = loader._insert_factors(conn, _frame(), id_map=id_map, source="baostock")
    assert n == 1
    params = conn.execute.call_args_list[1][0][1]
    assert params["revision"] == 1
