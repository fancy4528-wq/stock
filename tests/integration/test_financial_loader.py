"""Financial loader + PIT revision sentinel (integration)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.repository.pit import PITRepository
from quantagent.data.loaders import FinancialLoader
from quantagent.shared.errors import DataQualityError

CN = ZoneInfo("Asia/Shanghai")
pytestmark = pytest.mark.integration


def _frame(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = {
        "symbol": "600519.SH",
        "period_end": date(2019, 12, 31),
        "period_type": "FY",
        "announced_at": datetime(2020, 3, 31, 15, 0, tzinfo=CN),
        "report_type": "original",
        "revenue": 100.0,
        "operating_cost": 40.0,
        "gross_profit": 60.0,
        "operating_profit": 50.0,
        "net_profit": 40.0,
        "net_profit_attr": 39.0,
        "net_profit_deducted": 38.0,
        "eps": 1.0,
        "total_assets": 200.0,
        "total_liab": 80.0,
        "total_equity": 120.0,
        "equity_attr": 110.0,
        "cash_and_equiv": 10.0,
        "inventory": 5.0,
        "accounts_recv": 4.0,
        "goodwill": 1.0,
        "cfo": 30.0,
        "cfi": -10.0,
        "cff": -5.0,
        "capex": 8.0,
        "source": "test",
    }
    row.update(overrides)
    return pl.DataFrame([row])


def test_financial_loader_and_pit(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    loader = FinancialLoader(engine)
    result = loader.load(_frame(), source="test", target_date=date(2026, 9, 5))
    assert result["status"] == "success"
    assert result["rows_loaded"] == 1

    repo = PITRepository(engine)
    visible = repo.get_financials(["600519.SH"], as_of=date(2020, 6, 30), periods=4)
    assert visible.height == 1
    assert float(visible["net_profit"][0]) == 40.0

    # Restatement announced in the future must not leak into historical as_of.
    loader.load(
        _frame(
            announced_at=datetime(2021, 3, 31, 15, 0, tzinfo=CN),
            net_profit=999.0,
            revenue=100.0,
            total_assets=200.0,
        ),
        source="test",
        target_date=date(2026, 9, 5),
    )
    after = repo.get_financials(["600519.SH"], as_of=date(2020, 6, 30), periods=4)
    assert float(after["net_profit"][0]) == 40.0
    assert int(after["revision"][0]) == 1

    later = repo.get_financials(["600519.SH"], as_of=date(2021, 6, 30), periods=4)
    assert float(later["net_profit"][0]) == 999.0
    assert int(later["revision"][0]) == 2


def test_financial_loader_rejects_early_announce(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    bad = _frame(announced_at=datetime(2019, 1, 1, 15, 0, tzinfo=CN))
    with pytest.raises(DataQualityError, match="FIN_002"):
        FinancialLoader(engine).load(bad, source="test", target_date=date(2026, 9, 5))
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM financial_statement")).scalar_one()
    assert int(n) == 0
