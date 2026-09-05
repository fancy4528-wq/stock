"""Backtest future-function sentinel against Postgres prices."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.backtest import BuyAndHoldConfig, BuyAndHoldEngine
from quantagent.backtest.sentinel import assert_metrics_unchanged

pytestmark = pytest.mark.integration


def _seed_index_prices(engine: Engine, symbol: str = "000300.SH") -> None:
    with engine.begin() as conn:
        sid = conn.execute(
            text(
                """
                INSERT INTO security (market, symbol, raw_symbol, name, board)
                VALUES ('CN', :symbol, '000300', '沪深300', 'main')
                RETURNING security_id
                """
            ),
            {"symbol": symbol},
        ).scalar_one()
        rows = [
            (date(2020, 1, 2), 100.0),
            (date(2020, 1, 3), 101.0),
            (date(2020, 1, 6), 102.0),
            (date(2020, 1, 7), 103.0),
            (date(2020, 1, 8), 104.0),
        ]
        for d, px in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO price_daily (
                        security_id, trade_date, open, high, low, close, volume, source
                    ) VALUES (:sid, :d, :px, :px, :px, :px, 1000, 'test')
                    """
                ),
                {"sid": sid, "d": d, "px": px},
            )


def test_buyhold_ignores_future_prices(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    _seed_index_prices(engine)
    cfg = BuyAndHoldConfig(
        symbol="000300.SH",
        start=date(2020, 1, 2),
        end=date(2020, 1, 8),
    )
    engine_bt = BuyAndHoldEngine()
    baseline = engine_bt.run(cfg)

    with engine.begin() as conn:
        sid = conn.execute(
            text("SELECT security_id FROM security WHERE symbol = '000300.SH'")
        ).scalar_one()
        # Absurd future spike after the backtest window.
        conn.execute(
            text(
                """
                INSERT INTO price_daily (
                    security_id, trade_date, open, high, low, close, volume, source
                ) VALUES (:sid, '2030-01-02', 99999, 99999, 99999, 99999, 1, 'pollute')
                """
            ),
            {"sid": sid},
        )

    polluted = engine_bt.run(cfg)
    assert_metrics_unchanged(baseline, polluted)
