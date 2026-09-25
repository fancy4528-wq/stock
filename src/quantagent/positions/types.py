"""Manual position book types (P2a YAML-first)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class PositionLot(BaseModel):
    """One held security with cost basis for exit triggers."""

    symbol: str
    quantity: float
    avg_cost: float
    entry_date: date
    entry_high: float | None = None
    name: str | None = None
    industry: str | None = None  # optional SW L1 name/code for RISK_SECTOR_*

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol must be non-empty")
        return s

    @field_validator("quantity")
    @classmethod
    def _qty_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @field_validator("avg_cost")
    @classmethod
    def _cost_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("avg_cost must be > 0")
        return v


class WatchlistItem(BaseModel):
    """Non-holding symbol still monitored (target price etc.)."""

    symbol: str
    reason: str | None = None
    target_price: float | None = None
    name: str | None = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol must be non-empty")
        return s


class ManualPositionBook(BaseModel):
    """YAML-backed book for A-share stage (no broker API)."""

    account: str = "manual_cn"
    base_currency: str = "CNY"
    cash: float = 0.0
    as_of: date
    updated_at: datetime | None = None
    # For RISK_PORTFOLIO_DRAWDOWN — peak marked equity since tracking started.
    peak_nav: float | None = None
    positions: list[PositionLot] = Field(default_factory=list)
    watchlist: list[WatchlistItem] = Field(default_factory=list)

    def symbols(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for p in self.positions:
            if p.symbol not in seen:
                seen.add(p.symbol)
                out.append(p.symbol)
        for w in self.watchlist:
            if w.symbol not in seen:
                seen.add(w.symbol)
                out.append(w.symbol)
        return out

    def position_map(self) -> dict[str, PositionLot]:
        return {p.symbol: p for p in self.positions}

    def market_value(self, last_prices: dict[str, float]) -> float:
        total = float(self.cash)
        for p in self.positions:
            px = last_prices.get(p.symbol)
            if px is not None:
                total += p.quantity * px
        return total

    def weight(self, symbol: str, last_prices: dict[str, float]) -> float:
        mv = self.market_value(last_prices)
        if mv <= 0:
            return 0.0
        lot = self.position_map().get(symbol)
        if lot is None:
            return 0.0
        px = last_prices.get(symbol)
        if px is None:
            return 0.0
        return (lot.quantity * px) / mv
