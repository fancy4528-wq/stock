"""Integration constructions for MVP edge-case checklist G/E/A2."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.repository.pit import PITRepository
from quantagent.core.universe.config import seed_universe_snapshot
from quantagent.data.loaders import FinancialLoader
from quantagent.data.validators.pit import run_pit_checks
from quantagent.shared.errors import DataQualityError

CN = ZoneInfo("Asia/Shanghai")
pytestmark = pytest.mark.integration


def _seed_security(engine: Engine, symbol: str = "600519.SH") -> int:
    digits = symbol.split(".")[0]
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO security (market, symbol, raw_symbol, name, board, list_date)
                    VALUES ('CN', :symbol, :raw, :name, 'main', '2001-08-27')
                    RETURNING security_id
                    """
                ),
                {"symbol": symbol, "raw": digits, "name": symbol},
            ).scalar_one()
        )


def test_G2_pit001_announced_after_ingested(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    sid = _seed_security(engine)
    future = datetime.now(CN) + timedelta(days=30)
    past = datetime.now(CN) - timedelta(days=1)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO financial_statement (
                    security_id, period_end, period_type, revision, announced_at,
                    report_type, net_profit, source, ingested_at
                ) VALUES (
                    :sid, '2019-12-31', 'FY', 1, :ann, 'original', 1, 'test', :ing
                )
                """
            ),
            {"sid": sid, "ann": future, "ing": past},
        )
        report = run_pit_checks(conn)
    pit001 = next(r for r in report.results if r.code == "PIT_001")
    assert pit001.status == "fail"


def test_G3_pit003_overlapping_intervals(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    sid = _seed_security(engine)
    with engine.begin() as conn:
        tax_id = conn.execute(
            text(
                """
                INSERT INTO industry_taxonomy (code, name, market, levels)
                VALUES ('SW_TEST', '申万测试', 'CN', 3) RETURNING taxonomy_id
                """
            )
        ).scalar_one()
        ind_id = conn.execute(
            text(
                """
                INSERT INTO industry (taxonomy_id, code, name, level)
                VALUES (:t, '801010', '农林牧渔', 1) RETURNING industry_id
                """
            ),
            {"t": tax_id},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO security_industry
                    (security_id, industry_id, valid_from, valid_to, source)
                VALUES
                    (:sid, :iid, '2020-01-01', NULL, 'test'),
                    (:sid, :iid, '2021-01-01', NULL, 'test')
                """
            ),
            {"sid": sid, "iid": ind_id},
        )
        report = run_pit_checks(conn)
    pit003 = next(r for r in report.results if r.code == "PIT_003")
    assert pit003.status == "fail"


def test_G4_pit006_price_after_delist(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    with engine.begin() as conn:
        sid = conn.execute(
            text(
                """
                INSERT INTO security
                    (market, symbol, raw_symbol, name, board, list_date, delist_date)
                VALUES ('CN', '600001.SH', '600001', '退', 'main', '2000-01-01', '2020-06-01')
                RETURNING security_id
                """
            )
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO security_status_history
                    (security_id, status, name, valid_from, source)
                VALUES (:sid, 'delisted', '退', '2020-06-01', 'test')
                """
            ),
            {"sid": sid},
        )
        conn.execute(
            text(
                """
                INSERT INTO price_daily (
                    security_id, trade_date, open, high, low, close, volume, amount, source
                ) VALUES (:sid, '2020-07-01', 1, 1, 1, 1, 100, 100, 'test')
                """
            ),
            {"sid": sid},
        )
        report = run_pit_checks(conn)
    pit006 = next(r for r in report.results if r.code == "PIT_006")
    pit007 = next(r for r in report.results if r.code == "PIT_007")
    assert pit006.status == "warn"
    assert pit007.status == "pass"  # security row retained


def _fin_frame(**overrides: object) -> pl.DataFrame:
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


def test_E1_financial_revision_pit_visibility(clean_pit_tables: Engine) -> None:
    """E1: new revision does not overwrite; as_of before announce cannot see it."""
    engine = clean_pit_tables
    loader = FinancialLoader(engine)
    loader.load(_fin_frame(), source="test", target_date=date(2026, 9, 5))
    loader.load(
        _fin_frame(
            announced_at=datetime(2021, 3, 31, 15, 0, tzinfo=CN),
            net_profit=999.0,
        ),
        source="test",
        target_date=date(2026, 9, 5),
    )
    repo = PITRepository(engine)
    before = repo.get_financials(["600519.SH"], as_of=date(2020, 6, 30), periods=4)
    assert float(before["net_profit"][0]) == 40.0
    after = repo.get_financials(["600519.SH"], as_of=date(2021, 6, 30), periods=4)
    assert float(after["net_profit"][0]) == 999.0
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM financial_statement")).scalar_one()
    assert int(n) == 2  # append revision, no overwrite


def test_A2_seed_skips_suspended_symbol(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    as_of = date(2026, 9, 1)
    with engine.begin() as conn:
        for sym, sus in (("600519.SH", False), ("600000.SH", True)):
            sid = conn.execute(
                text(
                    """
                    INSERT INTO security (market, symbol, raw_symbol, name, board, list_date)
                    VALUES ('CN', :s, :r, :s, 'main', '2000-01-01')
                    RETURNING security_id
                    """
                ),
                {"s": sym, "r": sym.split(".")[0]},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO price_daily (
                        security_id, trade_date, open, high, low, close,
                        volume, amount, is_suspended, source
                    ) VALUES (
                        :sid, :d, 10, 10, 10, 10, :vol, 100, :sus, 'test'
                    )
                    """
                ),
                {
                    "sid": sid,
                    "d": as_of,
                    "vol": 0 if sus else 1000,
                    "sus": sus,
                },
            )
    result = seed_universe_snapshot(
        code="mvp_cn_50",
        as_of=as_of,
        symbols=["600519.SH", "600000.SH"],
        engine=engine,
    )
    assert "600000.SH" not in result["seeded"]
    assert "600519.SH" in result["seeded"]


def test_E3_loader_blocks_fin002(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    bad = _fin_frame(announced_at=datetime(2019, 1, 1, 15, 0, tzinfo=CN))
    with pytest.raises(DataQualityError, match="FIN_002"):
        FinancialLoader(engine).load(bad, source="test", target_date=date(2026, 9, 5))
