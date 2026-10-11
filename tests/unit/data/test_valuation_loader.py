"""Unit tests for valuation loader upsert path."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl

from quantagent.data.loaders.valuation import ValuationLoader


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "trade_date": [date(2024, 1, 2)],
            "pe_ttm": [20.0],
            "pb": [8.0],
            "ps_ttm": [10.0],
            "pe_lyr": [None],
            "market_cap": [None],
            "circ_market_cap": [None],
            "dividend_yield": [None],
            "source": ["baostock"],
        }
    )


def test_upsert_valuations_executes_insert() -> None:
    loader = ValuationLoader(engine=MagicMock())
    conn = MagicMock()
    id_map = {"600519.SH": 1}
    n = loader._upsert_valuations(conn, _frame(), id_map=id_map, source="baostock")
    assert n == 1
    payload = conn.execute.call_args[0][1]
    assert isinstance(payload, list)
    assert payload[0]["security_id"] == 1
    assert payload[0]["pe_ttm"] == 20.0
    assert payload[0]["pb"] == 8.0


def test_load_empty_raises() -> None:
    loader = ValuationLoader(engine=MagicMock())
    with patch.object(loader, "_start_batch", return_value=1):
        try:
            loader.load(pl.DataFrame(), source="baostock", target_date=date(2024, 1, 2))
            raised = False
        except Exception:
            raised = True
    assert raised
