"""Mock-based unit coverage for PITRepository (no Postgres)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.core.repository.pit import PITRepository
from quantagent.shared.errors import LookaheadError

CN_TZ = ZoneInfo("Asia/Shanghai")


def _repo() -> PITRepository:
    repo = PITRepository.__new__(PITRepository)
    repo._engine = MagicMock()
    return repo


def _connect_ctx(conn: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


def test_eod_maps_to_session_close() -> None:
    ts = PITRepository._eod(date(2020, 1, 2))
    assert ts == datetime(2020, 1, 2, 15, 0, tzinfo=CN_TZ)


def test_init_uses_settings_database_url() -> None:
    settings = MagicMock()
    settings.database_url = "postgresql+psycopg://x"
    with patch("quantagent.core.repository.pit.create_engine") as create:
        create.return_value = MagicMock()
        PITRepository(settings=settings)
    create.assert_called_once_with("postgresql+psycopg://x", pool_pre_ping=True)


def test_resolve_symbol_ids_empty_and_missing() -> None:
    repo = _repo()
    conn = MagicMock()
    assert repo._resolve_symbol_ids(conn, []) == {}

    result = MagicMock()
    result.__iter__ = lambda self: iter([SimpleNamespace(symbol="600519.SH", security_id=7)])
    conn.execute.return_value = result
    assert repo._resolve_symbol_ids(conn, ["600519.SH"]) == {"600519.SH": 7}

    with pytest.raises(KeyError, match="Unknown symbols"):
        repo._resolve_symbol_ids(conn, ["600519.SH", "999999.SH"])


def test_resolve_ids_preserves_order() -> None:
    repo = _repo()
    conn = MagicMock()
    with patch.object(
        repo,
        "_resolve_symbol_ids",
        return_value={"A": 1, "B": 2},
    ):
        assert repo._resolve_ids(conn, ["B", "A"]) == [2, 1]


def test_get_delisted_between_queries() -> None:
    repo = _repo()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [("600001.SH",), ("600002.SH",)]
    repo._engine.connect.return_value = _connect_ctx(conn)
    assert repo.get_delisted_between(date(2020, 1, 1), date(2020, 12, 31)) == [
        "600001.SH",
        "600002.SH",
    ]


def test_get_security_names() -> None:
    repo = _repo()
    assert repo.get_security_names([], as_of=date(2020, 1, 1)) == {}

    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {"symbol": "600519.SH", "name": "茅台"}
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    assert repo.get_security_names(["600519.SH"], as_of=date(2020, 1, 1)) == {
        "600519.SH": "茅台"
    }


def test_resolve_universe_symbols_empty_and_ordered() -> None:
    repo = _repo()
    with patch.object(repo, "get_universe", return_value=pl.DataFrame()):
        assert repo.resolve_universe_symbols(as_of=date(2020, 1, 1), name="mvp") == []

    uni = pl.DataFrame({"security_id": [2, 1]})
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {"security_id": 1, "symbol": "AAA"},
        {"security_id": 2, "symbol": "BBB"},
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    with patch.object(repo, "get_universe", return_value=uni):
        assert repo.resolve_universe_symbols(as_of=date(2020, 1, 1), name="mvp") == [
            "BBB",
            "AAA",
        ]


def test_list_universe_snapshot_dates() -> None:
    repo = _repo()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        (date(2020, 1, 1),),
        ("2020-02-01",),
        (None,),
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    assert repo.list_universe_snapshot_dates(name="mvp") == [
        date(2020, 1, 1),
        date(2020, 2, 1),
    ]


def test_latest_trade_date_paths() -> None:
    repo = _repo()
    assert repo.latest_trade_date([], as_of=date(2020, 1, 1)) is None

    conn = MagicMock()
    repo._engine.connect.return_value = _connect_ctx(conn)
    with patch.object(repo, "_resolve_ids", return_value=[]):
        assert repo.latest_trade_date(["x"], as_of=date(2020, 1, 1)) is None

    with patch.object(repo, "_resolve_ids", return_value=[1]):
        conn.execute.return_value.mappings.return_value.one.return_value = {"d": None}
        assert repo.latest_trade_date(["x"], as_of=date(2020, 1, 1)) is None

        conn.execute.return_value.mappings.return_value.one.return_value = {
            "d": date(2020, 1, 2)
        }
        assert repo.latest_trade_date(["x"], as_of=date(2020, 1, 3)) == date(2020, 1, 2)

        conn.execute.return_value.mappings.return_value.one.return_value = {"d": "2020-01-04"}
        assert repo.latest_trade_date(["x"], as_of=date(2020, 1, 5)) == date(2020, 1, 4)


def test_get_financials_empty_and_lookahead() -> None:
    repo = _repo()
    conn = MagicMock()
    repo._engine.connect.return_value = _connect_ctx(conn)

    with patch.object(repo, "_resolve_ids", return_value=[]):
        assert repo.get_financials(["x"], as_of=date(2020, 1, 1)).is_empty()

    with patch.object(repo, "_resolve_ids", return_value=[1]):
        conn.execute.return_value.mappings.return_value.all.return_value = []
        assert repo.get_financials(["x"], as_of=date(2020, 1, 1)).is_empty()

        conn.execute.return_value.mappings.return_value.all.return_value = [
            {
                "security_id": 1,
                "announced_at": datetime(2019, 6, 1, tzinfo=CN_TZ),
            }
        ]
        df = repo.get_financials(["x"], as_of=date(2020, 1, 1))
        assert "_as_of" in df.columns

        conn.execute.return_value.mappings.return_value.all.return_value = [
            {
                "security_id": 1,
                "announced_at": datetime(2021, 1, 1, tzinfo=CN_TZ),
            }
        ]
        with pytest.raises(LookaheadError):
            repo.get_financials(["x"], as_of=date(2020, 1, 1))


def test_get_prices_empty_and_symbol_map() -> None:
    repo = _repo()
    conn = MagicMock()
    repo._engine.connect.return_value = _connect_ctx(conn)

    with patch.object(repo, "_resolve_symbol_ids", return_value={}):
        assert repo.get_prices([], as_of=date(2020, 1, 2), start=date(2020, 1, 1)).is_empty()

    with patch.object(repo, "_resolve_symbol_ids", return_value={"600519.SH": 9}):
        conn.execute.return_value.mappings.return_value.all.return_value = []
        assert repo.get_prices(
            ["600519.SH"], as_of=date(2020, 1, 2), start=date(2020, 1, 1)
        ).is_empty()

        conn.execute.return_value.mappings.return_value.all.return_value = [
            {"security_id": 9, "trade_date": date(2020, 1, 1), "close": 10.0}
        ]
        df = repo.get_prices(
            ["600519.SH"],
            as_of=date(2020, 1, 2),
            start=date(2020, 1, 1),
            end=date(2020, 1, 2),
        )
        assert df["symbol"].to_list() == ["600519.SH"]
        assert "_as_of" in df.columns


def test_get_industry_and_universe() -> None:
    repo = _repo()
    conn = MagicMock()
    repo._engine.connect.return_value = _connect_ctx(conn)

    with patch.object(repo, "_resolve_symbol_ids", return_value={}):
        assert repo.get_industry([], as_of=date(2020, 1, 1)).is_empty()

    with patch.object(repo, "_resolve_symbol_ids", return_value={"600519.SH": 3}):
        conn.execute.return_value.mappings.return_value.all.return_value = [
            {
                "security_id": 3,
                "industry_id": 1,
                "valid_from": date(2019, 1, 1),
            }
        ]
        df = repo.get_industry(["600519.SH"], as_of=date(2020, 1, 1))
        assert df["symbol"].to_list() == ["600519.SH"]

        conn.execute.return_value.mappings.return_value.all.return_value = [
            {
                "security_id": 3,
                "industry_id": 1,
                "valid_from": date(2021, 1, 1),
            }
        ]
        with pytest.raises(LookaheadError):
            repo.get_industry(["600519.SH"], as_of=date(2020, 1, 1))

    conn.execute.return_value.mappings.return_value.all.return_value = []
    assert repo.get_universe(as_of=date(2020, 1, 1), name="mvp").is_empty()

    conn.execute.return_value.mappings.return_value.all.return_value = [
        {"security_id": 1, "snapshot_date": date(2019, 6, 1)}
    ]
    uni = repo.get_universe(as_of=date(2020, 1, 1), name="mvp")
    assert uni.height == 1

    conn.execute.return_value.mappings.return_value.all.return_value = [
        {"security_id": 1, "snapshot_date": date(2021, 1, 1)}
    ]
    with pytest.raises(LookaheadError):
        repo.get_universe(as_of=date(2020, 1, 1), name="mvp")
