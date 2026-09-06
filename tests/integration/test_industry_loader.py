"""Integration: industry taxonomy + membership load, PIT readback."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.repository.pit import PITRepository
from quantagent.data.loaders import IndustryLoader

pytestmark = pytest.mark.integration


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "record_type": "industry",
                "taxonomy_code": "sw_2021",
                "industry_code": "801080",
                "industry_name": "电子",
                "level": 1,
                "parent_code": None,
                "source": "akshare",
            },
            {
                "record_type": "membership",
                "taxonomy_code": "sw_2021",
                "symbol": "000725.SZ",
                "industry_code": "801080",
                "industry_name": "电子",
                "level": 1,
                "valid_from": date(2021, 12, 13),
                "valid_to": None,
                "source": "akshare",
            },
        ]
    )


def test_industry_loader_and_pit_read(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    with engine.begin() as conn:
        conn.execute(text("SELECT 1 FROM ingest_batch LIMIT 0"))

    result = IndustryLoader(engine).load(
        _frame(),
        source="akshare",
        target_date=date(2026, 9, 6),
    )
    assert result["status"] == "success"
    assert int(result["industries_upserted"]) == 1
    assert int(result["memberships_applied"]) == 1

    repo = PITRepository(engine)
    ind = repo.get_industry(["000725.SZ"], as_of=date(2026, 9, 6), taxonomy="sw_2021")
    assert ind.height == 1
    assert ind["industry_name"][0] == "电子"
    assert int(ind["level"][0]) == 1

    # Re-load same membership → no duplicate open interval
    result2 = IndustryLoader(engine).load(
        _frame(),
        source="akshare",
        target_date=date(2026, 9, 6),
    )
    assert int(result2["memberships_applied"]) == 0
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM security_industry")).scalar_one()
        assert int(n) == 1
