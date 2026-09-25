"""Load / save / mutate YAML position books (P2a)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from quantagent.positions.types import ManualPositionBook, PositionLot, WatchlistItem
from quantagent.shared.errors import ConfigError, DataError


def default_positions_path(account: str = "my_cn") -> Path:
    """Resolve ``data/positions/{account}.yaml`` from repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "data" / "positions" / f"{account}.yaml"
    raise ConfigError("Cannot locate repo root for data/positions/")


def load_position_book(path: Path | str) -> ManualPositionBook:
    """Parse a position YAML file into ``ManualPositionBook``."""
    p = Path(path)
    if not p.is_file():
        raise DataError(f"position book not found: {p}")
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid position book (expected mapping): {p}")
    return ManualPositionBook.model_validate(raw)


def save_position_book(book: ManualPositionBook, path: Path | str) -> Path:
    """Write book to YAML; stamps ``updated_at`` to now (UTC)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamped = book.model_copy(update={"updated_at": datetime.now(UTC)})
    payload = stamped.model_dump(mode="json")
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    p.write_text(text, encoding="utf-8")
    return p


def add_position(
    book: ManualPositionBook,
    *,
    symbol: str,
    quantity: float,
    avg_cost: float,
    entry_date: date | None = None,
    name: str | None = None,
) -> ManualPositionBook:
    """Return a copy with ``symbol`` upserted (replaces existing lot)."""
    lot = PositionLot(
        symbol=symbol,
        quantity=quantity,
        avg_cost=avg_cost,
        entry_date=entry_date or book.as_of,
        name=name,
        entry_high=avg_cost,
    )
    others = [p for p in book.positions if p.symbol != lot.symbol]
    return book.model_copy(update={"positions": [*others, lot], "as_of": book.as_of})


def remove_position(book: ManualPositionBook, symbol: str) -> ManualPositionBook:
    """Return a copy without ``symbol``."""
    sym = symbol.strip().upper()
    return book.model_copy(
        update={"positions": [p for p in book.positions if p.symbol != sym]}
    )


def add_watchlist(
    book: ManualPositionBook,
    *,
    symbol: str,
    target_price: float | None = None,
    reason: str | None = None,
    name: str | None = None,
) -> ManualPositionBook:
    item = WatchlistItem(
        symbol=symbol, target_price=target_price, reason=reason, name=name
    )
    others = [w for w in book.watchlist if w.symbol != item.symbol]
    return book.model_copy(update={"watchlist": [*others, item]})
