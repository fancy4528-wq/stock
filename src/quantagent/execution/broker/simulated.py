"""In-memory SimulatedBroker with A-share matching constraints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.execution.broker.base import (
    AccountInfo,
    BrokerAdapter,
    BrokerCapabilities,
    BrokerOrderState,
    BrokerPosition,
    CancelAck,
    OrderAck,
    OrderRequest,
)
from quantagent.execution.orders.idempotency import InMemoryIdempotencyGuard
from quantagent.execution.orders.state_machine import transition
from quantagent.shared.errors import QuantAgentError


class FaultConfig(BaseModel):
    timeout_rate: float = 0.0
    reject_rate: float = 0.0
    partial_fill_rate: float = 0.0
    duplicate_ack_rate: float = 0.0
    stale_position_rate: float = 0.0
    force_timeout_ids: set[str] = Field(default_factory=set)
    force_reject_ids: set[str] = Field(default_factory=set)
    force_partial_ids: set[str] = Field(default_factory=set)


class PriceBar(BaseModel):
    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    is_suspended: bool = False
    is_limit_up: bool = False
    is_limit_down: bool = False


class FillDecision(BaseModel):
    kind: Literal["full", "partial", "reject"]
    quantity: float = 0.0
    reason: str | None = None


class UnfilledRecord(BaseModel):
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    reason: str
    trade_date: date | None = None


class SimulatedBroker(BrokerAdapter):
    """Matching engine for backtest / Shadow / unit tests. Not live."""

    is_live = False

    def __init__(
        self,
        market_cfg: MarketConfig | None = None,
        *,
        cash: float = 1_000_000.0,
        fault_injection: FaultConfig | None = None,
        market_open: bool = True,
    ) -> None:
        self._market = market_cfg or load_market_config("CN")
        self.market = self._market.market
        self._cash = float(cash)
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, BrokerOrderState] = {}
        self._bars: dict[str, PriceBar] = {}
        self._trade_date: date | None = None
        self._fault = fault_injection or FaultConfig()
        self._guard = InMemoryIdempotencyGuard()
        self._market_open = market_open
        self.unfilled: list[UnfilledRecord] = []
        self._seq = 0

    def set_bars(self, bars: list[PriceBar], *, trade_date: date | None = None) -> None:
        self._bars = {b.symbol: b for b in bars}
        if trade_date is not None:
            self._trade_date = trade_date
        elif bars:
            self._trade_date = bars[0].trade_date

    def roll_day(self) -> None:
        """Mark all holdings sellable (T+1 unlock at next session)."""
        for pos in self._positions.values():
            pos.sellable_qty = pos.quantity

    def _can_fill(self, order: OrderRequest, bar: PriceBar) -> FillDecision:
        if bar.is_suspended:
            return FillDecision(kind="reject", reason="suspended")

        if order.side == "buy" and bar.is_limit_up:
            return FillDecision(kind="reject", reason="limit_up_cannot_buy")
        if order.side == "sell" and bar.is_limit_down:
            return FillDecision(kind="reject", reason="limit_down_cannot_sell")

        qty = float(order.quantity)
        if order.side == "sell" and not self._market.same_day_sell_allowed:
            sellable = self._positions.get(order.symbol)
            avail = 0.0 if sellable is None else float(sellable.sellable_qty)
            if qty > avail + 1e-9:
                if avail <= 0:
                    return FillDecision(kind="reject", reason="t1_not_sellable")
                qty = avail
                return FillDecision(kind="partial", quantity=qty, reason="t1_clip")

        max_qty = bar.volume * self._market.slippage.max_volume_share
        if max_qty > 0 and qty > max_qty:
            return FillDecision(kind="partial", quantity=max_qty, reason="volume_limit")

        if order.order_type == "limit" and order.limit_price is not None:
            if order.side == "buy" and order.limit_price < bar.low:
                return FillDecision(kind="reject", reason="limit_price_not_reached")
            if order.side == "sell" and order.limit_price > bar.high:
                return FillDecision(kind="reject", reason="limit_price_not_reached")

        return FillDecision(kind="full", quantity=qty)

    def _fill_price(self, order: OrderRequest, bar: PriceBar) -> float:
        bps = self._market.slippage.fixed_bps / 10_000.0
        if order.side == "buy":
            px = bar.open * (1.0 + bps)
        else:
            px = bar.open * (1.0 - bps)
        if order.order_type == "limit" and order.limit_price is not None:
            if order.side == "buy":
                px = min(px, order.limit_price)
            else:
                px = max(px, order.limit_price)
        return float(px)

    def _apply_fill(self, order: OrderRequest, qty: float, price: float) -> tuple[float, float]:
        notional = qty * price
        fees = self._market.estimate_fees(side=order.side, notional=notional, quantity=qty)
        if order.side == "buy":
            cost = notional + fees
            if cost > self._cash + 1e-6:
                raise QuantAgentError("insufficient cash")
            self._cash -= cost
            pos = self._positions.get(order.symbol)
            if pos is None:
                self._positions[order.symbol] = BrokerPosition(
                    symbol=order.symbol,
                    quantity=qty,
                    sellable_qty=0.0 if not self._market.same_day_sell_allowed else qty,
                    avg_cost=price,
                    market_value=notional,
                )
            else:
                new_qty = pos.quantity + qty
                pos.avg_cost = (
                    (pos.avg_cost * pos.quantity + notional) / new_qty if new_qty else 0.0
                )
                pos.quantity = new_qty
                if self._market.same_day_sell_allowed:
                    pos.sellable_qty += qty
                pos.market_value = pos.quantity * price
        else:
            pos = self._positions.get(order.symbol)
            if pos is None or pos.quantity + 1e-9 < qty:
                raise QuantAgentError("insufficient position")
            proceeds = notional - fees
            self._cash += proceeds
            pos.quantity -= qty
            pos.sellable_qty = max(0.0, pos.sellable_qty - qty)
            if pos.quantity <= 1e-9:
                del self._positions[order.symbol]
            else:
                pos.market_value = pos.quantity * price
        return qty, fees

    async def _place_inner(self, req: OrderRequest) -> OrderAck:
        if req.client_order_id in self._fault.force_timeout_ids:
            raise TimeoutError(f"injected timeout for {req.client_order_id}")

        state = BrokerOrderState(
            client_order_id=req.client_order_id,
            broker_order_id=None,
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            status="submitting",
        )
        self._orders[req.client_order_id] = state

        if req.client_order_id in self._fault.force_reject_ids:
            state.status = transition("submitting", "rejected")
            state.reject_reason = "fault_reject"
            self.unfilled.append(
                UnfilledRecord(
                    client_order_id=req.client_order_id,
                    symbol=req.symbol,
                    side=req.side,
                    quantity=req.quantity,
                    reason="fault_reject",
                    trade_date=self._trade_date,
                )
            )
            return OrderAck(
                client_order_id=req.client_order_id,
                accepted=False,
                reject_reason="fault_reject",
            )

        bar = self._bars.get(req.symbol)
        if bar is None:
            state.status = transition("submitting", "rejected")
            state.reject_reason = "no_bar"
            self.unfilled.append(
                UnfilledRecord(
                    client_order_id=req.client_order_id,
                    symbol=req.symbol,
                    side=req.side,
                    quantity=req.quantity,
                    reason="no_bar",
                    trade_date=self._trade_date,
                )
            )
            return OrderAck(
                client_order_id=req.client_order_id,
                accepted=False,
                reject_reason="no_bar",
            )

        decision = self._can_fill(req, bar)
        if decision.kind == "reject":
            reason = decision.reason or "rejected"
            state.status = transition("submitting", "rejected")
            state.reject_reason = reason
            self.unfilled.append(
                UnfilledRecord(
                    client_order_id=req.client_order_id,
                    symbol=req.symbol,
                    side=req.side,
                    quantity=req.quantity,
                    reason=reason,
                    trade_date=self._trade_date,
                )
            )
            return OrderAck(
                client_order_id=req.client_order_id,
                accepted=False,
                reject_reason=reason,
            )

        fill_qty = decision.quantity if decision.kind == "partial" else float(req.quantity)
        if req.client_order_id in self._fault.force_partial_ids and fill_qty > 1:
            fill_qty = max(1.0, fill_qty // 2)

        price = self._fill_price(req, bar)
        try:
            filled, fees = self._apply_fill(req, fill_qty, price)
        except QuantAgentError as exc:
            state.status = transition("submitting", "rejected")
            state.reject_reason = str(exc)
            self.unfilled.append(
                UnfilledRecord(
                    client_order_id=req.client_order_id,
                    symbol=req.symbol,
                    side=req.side,
                    quantity=req.quantity,
                    reason=str(exc),
                    trade_date=self._trade_date,
                )
            )
            return OrderAck(
                client_order_id=req.client_order_id,
                accepted=False,
                reject_reason=str(exc),
            )

        broker_id = f"SIM-{uuid.uuid4().hex[:10]}"
        state.broker_order_id = broker_id
        state.filled_qty = filled
        state.avg_price = price
        if filled + 1e-9 < req.quantity:
            state.status = transition("submitting", "submitted")
            state.status = transition("submitted", "partial")
            if decision.reason:
                self.unfilled.append(
                    UnfilledRecord(
                        client_order_id=req.client_order_id,
                        symbol=req.symbol,
                        side=req.side,
                        quantity=req.quantity - filled,
                        reason=decision.reason,
                        trade_date=self._trade_date,
                    )
                )
        else:
            state.status = transition("submitting", "submitted")
            state.status = transition("submitted", "filled")

        return OrderAck(
            client_order_id=req.client_order_id,
            broker_order_id=broker_id,
            accepted=True,
            filled_qty=filled,
            avg_price=price,
            fees=fees,
        )

    async def get_account(self) -> AccountInfo:
        equity = self._cash + sum(p.market_value for p in self._positions.values())
        return AccountInfo(cash=self._cash, equity=equity, currency=self._market.currency)

    async def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    async def place_order(self, req: OrderRequest) -> OrderAck:
        return await self._guard.place_once(req, self._place_inner)

    async def cancel_order(self, client_order_id: str) -> CancelAck:
        order = self._orders.get(client_order_id)
        if order is None:
            return CancelAck(client_order_id=client_order_id, cancelled=False, reason="not_found")
        if order.status in {"filled", "cancelled", "expired", "rejected", "risk_rejected"}:
            return CancelAck(
                client_order_id=client_order_id,
                cancelled=False,
                reason=f"terminal:{order.status}",
            )
        try:
            if order.status == "submitted":
                order.status = transition("submitted", "cancelled")
            elif order.status == "partial":
                order.status = transition("partial", "cancelled")
            else:
                return CancelAck(
                    client_order_id=client_order_id,
                    cancelled=False,
                    reason=f"cannot_cancel:{order.status}",
                )
        except QuantAgentError as exc:
            return CancelAck(client_order_id=client_order_id, cancelled=False, reason=str(exc))
        return CancelAck(client_order_id=client_order_id, cancelled=True)

    async def get_order(self, client_order_id: str) -> BrokerOrderState:
        order = self._orders.get(client_order_id)
        if order is None:
            raise QuantAgentError(f"order not found: {client_order_id}")
        return order

    async def list_orders(self, *, since: datetime | None = None) -> list[BrokerOrderState]:
        _ = since
        return list(self._orders.values())

    async def is_market_open(self) -> bool:
        return self._market_open

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_limit_order=True,
            supports_fractional=self._market.allow_fractional,
            supports_short=self._market.short_selling_allowed,
            supports_cancel=True,
            supports_partial_fill=True,
            idempotent_place_order=True,
        )
