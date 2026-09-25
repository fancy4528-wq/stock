"""Unit tests: manual position YAML + staleness."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from quantagent.positions.manual import (
    add_position,
    load_position_book,
    remove_position,
    save_position_book,
)
from quantagent.positions.staleness import check_staleness
from quantagent.positions.types import ManualPositionBook, PositionLot
from quantagent.shared.errors import DataError


def test_load_example_book() -> None:
    root = Path(__file__).resolve().parents[3]
    book = load_position_book(root / "data" / "positions" / "example_cn.yaml")
    assert book.account == "manual_cn"
    assert len(book.positions) == 2
    assert "600519.SH" in book.symbols()
    assert book.position_map()["600519.SH"].avg_cost == 1680.0


def test_roundtrip_save(tmp_path: Path) -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        cash=1000,
        positions=[
            PositionLot(
                symbol="600519.SH",
                quantity=100,
                avg_cost=1600,
                entry_date=date(2026, 7, 1),
            )
        ],
    )
    path = tmp_path / "pos.yaml"
    save_position_book(book, path)
    loaded = load_position_book(path)
    assert loaded.updated_at is not None
    assert loaded.positions[0].symbol == "600519.SH"


def test_add_remove_position() -> None:
    book = ManualPositionBook(account="t", as_of=date(2026, 9, 18))
    book = add_position(book, symbol="000001.SZ", quantity=1000, avg_cost=10.5)
    assert len(book.positions) == 1
    book = remove_position(book, "000001.SZ")
    assert book.positions == []


def test_missing_file() -> None:
    with pytest.raises(DataError):
        load_position_book("/no/such/positions.yaml")


def test_staleness_calendar_fallback() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 1),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    fresh = check_staleness(book, reference=date(2026, 9, 3), max_trading_days=5)
    assert not fresh.stale
    stale = check_staleness(book, reference=date(2026, 9, 20), max_trading_days=5)
    assert stale.stale


def test_staleness_trading_days() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 1),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    opens = [
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 5),
        date(2026, 9, 8),
        date(2026, 9, 9),
    ]
    r = check_staleness(
        book, reference=date(2026, 9, 9), max_trading_days=5, open_dates=opens
    )
    assert r.age_trading_days == 6
    assert r.stale


def test_invalid_quantity() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PositionLot(
            symbol="600519.SH",
            quantity=0,
            avg_cost=10,
            entry_date=date(2026, 1, 1),
        )


def test_weight() -> None:
    book = ManualPositionBook(
        account="t",
        as_of=date(2026, 9, 18),
        cash=0,
        positions=[
            PositionLot(
                symbol="AAA.SH",
                quantity=100,
                avg_cost=10,
                entry_date=date(2026, 1, 1),
            ),
            PositionLot(
                symbol="BBB.SZ",
                quantity=100,
                avg_cost=10,
                entry_date=date(2026, 1, 1),
            ),
        ],
    )
    w = book.weight("AAA.SH", {"AAA.SH": 10.0, "BBB.SZ": 10.0})
    assert abs(w - 0.5) < 1e-9
