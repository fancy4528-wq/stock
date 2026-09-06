"""BrokerAdapter abstract interface and shared contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    client_order_id: str = Field(description="Idempotency key generated locally")
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    time_in_force: Literal["day", "gtc", "ioc"] = "day"


class OrderAck(BaseModel):
    client_order_id: str
    broker_order_id: str | None = None
    accepted: bool
    reject_reason: str | None = None
    is_duplicate: bool = False
    filled_qty: float = 0.0
    avg_price: float | None = None
    fees: float = 0.0


class CancelAck(BaseModel):
    client_order_id: str
    cancelled: bool
    reason: str | None = None


class BrokerCapabilities(BaseModel):
    supports_limit_order: bool = True
    supports_fractional: bool = False
    supports_short: bool = False
    supports_cancel: bool = True
    supports_partial_fill: bool = True
    min_order_value: float | None = None
    max_order_value: float | None = None
    idempotent_place_order: bool = True


class AccountInfo(BaseModel):
    cash: float
    equity: float
    currency: str = "CNY"


class BrokerPosition(BaseModel):
    symbol: str
    quantity: float
    sellable_qty: float
    avg_cost: float = 0.0
    market_value: float = 0.0


class BrokerOrderState(BaseModel):
    client_order_id: str
    broker_order_id: str | None = None
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    filled_qty: float = 0.0
    status: str
    avg_price: float | None = None
    reject_reason: str | None = None


class BrokerAdapter(ABC):
    """Business code depends only on this abstraction."""

    market: str
    is_live: bool

    @abstractmethod
    async def get_account(self) -> AccountInfo: ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]: ...

    @abstractmethod
    async def place_order(self, req: OrderRequest) -> OrderAck:
        """Must be idempotent on client_order_id."""

    @abstractmethod
    async def cancel_order(self, client_order_id: str) -> CancelAck: ...

    @abstractmethod
    async def get_order(self, client_order_id: str) -> BrokerOrderState: ...

    @abstractmethod
    async def list_orders(self, *, since: datetime | None = None) -> list[BrokerOrderState]: ...

    @abstractmethod
    async def is_market_open(self) -> bool: ...

    @abstractmethod
    def capabilities(self) -> BrokerCapabilities: ...
