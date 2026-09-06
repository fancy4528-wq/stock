"""Factor protocol and shared input contract.

Factors are pure functions: they never query the database. Callers must supply
Point-in-Time panels already filtered with ``as_of``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import ClassVar

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from quantagent.shared.errors import QuantAgentError


class FactorError(QuantAgentError):
    """Invalid factor input or computation failure."""


class FactorInput(BaseModel):
    """Panel inputs already filtered to what was visible at ``as_of``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    prices: pl.DataFrame
    financials: pl.DataFrame | None = None
    valuations: pl.DataFrame | None = None
    money_flow: pl.DataFrame | None = None
    events: pl.DataFrame | None = None
    industry: pl.DataFrame | None = None
    as_of: date
    meta: dict[str, object] = Field(default_factory=dict)


def entity_col(df: pl.DataFrame) -> str:
    """Prefer ``security_id``; fall back to ``symbol`` for constructed panels."""
    if "security_id" in df.columns:
        return "security_id"
    if "symbol" in df.columns:
        return "symbol"
    raise FactorError("prices must contain security_id or symbol")


def require_columns(df: pl.DataFrame, columns: list[str], *, context: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise FactorError(f"{context} missing columns: {sorted(missing)}")


def sorted_prices(prices: pl.DataFrame) -> pl.DataFrame:
    ent = entity_col(prices)
    require_columns(prices, [ent, "trade_date"], context="prices")
    return prices.sort([ent, "trade_date"])


class Factor(ABC):
    """Base class for versioned, pure factor computations."""

    code: ClassVar[str]
    name: ClassVar[str]
    category: ClassVar[str]
    version: ClassVar[str] = "v1"
    lookback_days: ClassVar[int]
    required_columns: ClassVar[list[str]]

    def compute(self, data: FactorInput) -> pl.Series:
        """Return a Series aligned to prices sorted by entity, trade_date."""
        prices = sorted_prices(data.prices)
        require_columns(prices, self.required_columns, context=self.code)
        values = self._compute(prices, data)
        if values.len() != prices.height:
            raise FactorError(f"{self.code}: expected {prices.height} values, got {values.len()}")
        return values.alias(self.code)

    @abstractmethod
    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series: ...

    def compute_frame(self, data: FactorInput) -> pl.DataFrame:
        """Return entity + trade_date + factor column."""
        prices = sorted_prices(data.prices)
        ent = entity_col(prices)
        series = self.compute(data)
        return prices.select([ent, "trade_date"]).with_columns(series)
