"""Future-function sentinel tests against live Postgres + PIT SQL."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.repository.pit import PITRepository

CN = ZoneInfo("Asia/Shanghai")
pytestmark = pytest.mark.integration


def _seed_security(engine: Engine) -> tuple[int, str]:
    symbol = "600519.SH"
    with engine.begin() as conn:
        sec_id = conn.execute(
            text(
                """
                INSERT INTO security (market, symbol, raw_symbol, name, board, list_date)
                VALUES ('CN', :symbol, '600519', '贵州茅台', 'main', '2001-08-27')
                RETURNING security_id
                """
            ),
            {"symbol": symbol},
        ).scalar_one()
    return int(sec_id), symbol


def test_financials_ignore_future_announcement(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    sec_id, symbol = _seed_security(engine)
    as_of = date(2020, 6, 30)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO financial_statement (
                    security_id, period_end, period_type, revision, announced_at,
                    report_type, net_profit, source
                ) VALUES
                (:sid, '2019-12-31', 'FY', 1, :past, 'original', 100, 'test'),
                (:sid, '2019-12-31', 'FY', 2, :future, 'restated', 999999, 'test')
                """
            ),
            {
                "sid": sec_id,
                "past": datetime(2020, 3, 31, 15, 0, tzinfo=CN),
                "future": datetime(2021, 3, 31, 15, 0, tzinfo=CN),
            },
        )

    repo = PITRepository(engine)
    before = repo.get_financials([symbol], as_of=as_of, periods=4)
    assert before.height == 1
    assert before["net_profit"][0] == Decimal("100.00") or before["net_profit"][0] == 100

    # Inject absurd future restatement — historical as_of must not change.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO financial_statement (
                    security_id, period_end, period_type, revision, announced_at,
                    report_type, net_profit, source
                ) VALUES
                (:sid, '2019-12-31', 'FY', 3, :far_future, 'restated', -1, 'test')
                """
            ),
            {
                "sid": sec_id,
                "far_future": datetime(2030, 1, 1, 15, 0, tzinfo=CN),
            },
        )

    after = repo.get_financials([symbol], as_of=as_of, periods=4)
    assert after.height == before.height
    assert after["net_profit"].to_list() == before["net_profit"].to_list()
    assert after["revision"].to_list() == before["revision"].to_list()


def test_prices_ignore_future_adjust_factor(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    sec_id, symbol = _seed_security(engine)
    as_of = date(2020, 1, 10)
    trade = date(2020, 1, 10)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO price_daily (
                    security_id, trade_date, open, high, low, close, volume, source
                ) VALUES (:sid, :d, 10, 10, 10, 10, 1000, 'test')
                """
            ),
            {"sid": sec_id, "d": trade},
        )
        conn.execute(
            text(
                """
                INSERT INTO adjust_factor (
                    security_id, trade_date, revision, announced_at,
                    factor_qfq, factor_hfq, source
                ) VALUES
                (:sid, :d, 1, :past, 1.0, 1.0, 'test'),
                (:sid, :d, 2, :future, 100.0, 100.0, 'test')
                """
            ),
            {
                "sid": sec_id,
                "d": trade,
                "past": datetime(2020, 1, 10, 15, 0, tzinfo=CN),
                "future": datetime(2025, 1, 1, 15, 0, tzinfo=CN),
            },
        )

    repo = PITRepository(engine)
    before = repo.get_prices([symbol], as_of=as_of, start=trade, end=trade)
    assert before.height == 1
    assert float(before["close"][0]) == 10.0

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO adjust_factor (
                    security_id, trade_date, revision, announced_at,
                    factor_qfq, factor_hfq, source
                ) VALUES (:sid, :d, 3, :far, 999.0, 999.0, 'test')
                """
            ),
            {
                "sid": sec_id,
                "d": trade,
                "far": datetime(2030, 6, 1, 15, 0, tzinfo=CN),
            },
        )

    after = repo.get_prices([symbol], as_of=as_of, start=trade, end=trade)
    assert after["close"].to_list() == before["close"].to_list()


def test_universe_uses_historical_snapshot(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    with engine.begin() as conn:
        a = conn.execute(
            text(
                """
                INSERT INTO security (market, symbol, raw_symbol, name)
                VALUES ('CN', 'AAA.SH', 'AAA', 'A') RETURNING security_id
                """
            )
        ).scalar_one()
        b = conn.execute(
            text(
                """
                INSERT INTO security (market, symbol, raw_symbol, name)
                VALUES ('CN', 'BBB.SH', 'BBB', 'B') RETURNING security_id
                """
            )
        ).scalar_one()
        uid = conn.execute(
            text(
                """
                INSERT INTO universe (code, name, market)
                VALUES ('mvp_cn_50', 'MVP', 'CN') RETURNING universe_id
                """
            )
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO universe_snapshot (universe_id, snapshot_date, security_id, weight)
                VALUES
                (:u, '2018-01-01', :a, 1.0),
                (:u, '2024-01-01', :b, 1.0)
                """
            ),
            {"u": uid, "a": a, "b": b},
        )

    repo = PITRepository(engine)
    hist = repo.get_universe(as_of=date(2019, 6, 1), name="mvp_cn_50")
    assert hist.height == 1
    assert int(hist["security_id"][0]) == int(a)

    # Future membership must not leak into historical as_of.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO universe_snapshot (universe_id, snapshot_date, security_id, weight)
                VALUES (:u, '2025-01-01', :b, 1.0)
                """
            ),
            {"u": uid, "b": b},
        )

    hist2 = repo.get_universe(as_of=date(2019, 6, 1), name="mvp_cn_50")
    assert hist2["security_id"].to_list() == hist["security_id"].to_list()
