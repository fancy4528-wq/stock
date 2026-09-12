"""Survivorship-bias checks for PITRepository."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quantagent.core.repository.pit import PITRepository

pytestmark_integration = pytest.mark.integration


def test_get_security_names_and_latest_trade_date_keyword_only() -> None:
    repo = PITRepository.__new__(PITRepository)
    with pytest.raises(TypeError):
        repo.get_security_names(["600519.SH"])  # type: ignore[misc]
    with pytest.raises(TypeError):
        repo.latest_trade_date(["600519.SH"])  # type: ignore[misc]


def test_get_delisted_between_empty_range() -> None:
    repo = PITRepository.__new__(PITRepository)
    repo._engine = MagicMock()
    assert repo.get_delisted_between(date(2020, 6, 1), date(2020, 1, 1)) == []


@pytest.mark.integration
def test_get_delisted_between_returns_symbols(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO security
                    (market, symbol, raw_symbol, name, board, list_date, delist_date)
                VALUES
                    ('CN', '600001.SH', '600001', '退A', 'main', '2000-01-01', '2020-06-01'),
                    ('CN', '600002.SH', '600002', '退B', 'main', '2000-01-01', '2020-08-15'),
                    ('CN', '600519.SH', '600519', '在', 'main', '2001-08-27', NULL)
                """
            )
        )
    repo = PITRepository(engine)
    found = repo.get_delisted_between(date(2020, 5, 1), date(2020, 7, 1))
    assert found == ["600001.SH"]
    assert repo.get_delisted_between(date(2020, 6, 1), date(2020, 8, 31)) == [
        "600001.SH",
        "600002.SH",
    ]


@pytest.mark.integration
def test_universe_contains_delisted(clean_pit_tables: Engine) -> None:
    """Historical snapshot may include a name that delists later; intersection is non-empty."""
    engine = clean_pit_tables
    snapshot_date = date(2020, 3, 1)
    delist_date = date(2020, 6, 1)
    with engine.begin() as conn:
        sid = conn.execute(
            text(
                """
                INSERT INTO security
                    (market, symbol, raw_symbol, name, board, list_date, delist_date)
                VALUES ('CN', '600001.SH', '600001', '退', 'main', '2000-01-01', :delist)
                RETURNING security_id
                """
            ),
            {"delist": delist_date},
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
                VALUES (:u, :d, :sid, 1.0)
                """
            ),
            {"u": uid, "d": snapshot_date, "sid": sid},
        )

    repo = PITRepository(engine)
    symbols = repo.resolve_universe_symbols(as_of=snapshot_date, name="mvp_cn_50")
    assert "600001.SH" in symbols

    delisted = set(repo.get_delisted_between(date(2020, 5, 1), date(2020, 7, 1)))
    overlap = set(symbols) & delisted
    assert overlap == {"600001.SH"}
