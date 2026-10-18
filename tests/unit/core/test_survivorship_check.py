"""Survivorship overlap: a historical snapshot must include a later delisting."""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.core.universe.survivorship import (
    SurvivorshipBiasError,
    check_universe_contains_delisted,
    later_delisted_symbols,
)
from quantagent.data.collectors.baostock.basic import delist_record_from_basic
from quantagent.shared.errors import QuantAgentError


class _Repo:
    def __init__(self, universe: list[str], delisted: list[str]) -> None:
        self.universe = universe
        self.delisted = delisted
        self.seen: tuple[date, date] | None = None

    def resolve_universe_symbols(self, *, as_of: date, name: str) -> list[str]:
        assert name == "csi300"
        assert as_of == date(2018, 1, 31)
        return list(self.universe)

    def get_delisted_between(self, start: date, end: date) -> list[str]:
        self.seen = (start, end)
        return list(self.delisted)


def test_later_delisted_symbols_is_sorted_intersection() -> None:
    assert later_delisted_symbols(
        ["600519.SH", "002450.SZ", "600074.SH", "002450.SZ"],
        ["600074.SH", "000024.SZ", "002450.SZ"],
    ) == ["002450.SZ", "600074.SH"]


def test_check_requires_later_delisting() -> None:
    repo = _Repo(["600519.SH", "002450.SZ"], ["002450.SZ"])
    report = check_universe_contains_delisted(
        repo,
        name="csi300",
        as_of=date(2018, 1, 31),
        until=date(2026, 10, 13),
    )
    assert report.symbols == ["002450.SZ"]
    assert report.n_universe == 2
    assert repo.seen == (date(2018, 2, 1), date(2026, 10, 13))


def test_check_rejects_pool_with_no_later_delisting() -> None:
    repo = _Repo(["600519.SH"], ["000693.SZ"])
    with pytest.raises(SurvivorshipBiasError, match="contains no name"):
        check_universe_contains_delisted(
            repo,
            name="csi300",
            as_of=date(2018, 1, 31),
            until=date(2026, 10, 13),
        )


def test_check_rejects_empty_snapshot() -> None:
    repo = _Repo([], ["002450.SZ"])
    with pytest.raises(SurvivorshipBiasError, match="no snapshot"):
        check_universe_contains_delisted(
            repo,
            name="csi300",
            as_of=date(2018, 1, 31),
            until=date(2026, 10, 13),
        )


def test_check_rejects_until_on_snapshot_date() -> None:
    repo = _Repo(["002450.SZ"], ["002450.SZ"])
    with pytest.raises(QuantAgentError, match="until must be after"):
        check_universe_contains_delisted(
            repo,
            name="csi300",
            as_of=date(2018, 1, 31),
            until=date(2018, 1, 31),
        )


def test_basic_row_skips_listed_names() -> None:
    assert (
        delist_record_from_basic(
            "000401.SZ",
            {
                "code_name": "冀东水泥",
                "ipoDate": "1996-06-14",
                "outDate": "",
                "status": "1",
            },
        )
        is None
    )


def test_basic_row_reads_delisting() -> None:
    record = delist_record_from_basic(
        "002450.SZ",
        {
            "code_name": "康得新",
            "ipoDate": "2010-07-16",
            "outDate": "2021-05-31",
            "status": "0",
        },
    )
    assert record is not None
    assert record.name == "康得新"
    assert record.list_date == date(2010, 7, 16)
    assert record.delist_date == date(2021, 5, 31)


def test_basic_row_rejects_delist_before_list() -> None:
    with pytest.raises(QuantAgentError, match="before list_date"):
        delist_record_from_basic(
            "002450.SZ",
            {
                "code_name": "康得新",
                "ipoDate": "2021-05-31",
                "outDate": "2010-07-16",
                "status": "0",
            },
        )
