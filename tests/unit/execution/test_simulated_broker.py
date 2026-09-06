"""Unit tests for SimulatedBroker, idempotency, and order state machine (W7)."""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.execution.broker import OrderRequest, PriceBar, SimulatedBroker
from quantagent.execution.orders import (
    InMemoryIdempotencyGuard,
    InvalidTransition,
    make_client_order_id,
    transition,
)


@pytest.fixture
def broker() -> SimulatedBroker:
    return SimulatedBroker(cash=1_000_000.0)


def _bar(
    symbol: str = "600000.SH",
    *,
    is_suspended: bool = False,
    is_limit_up: bool = False,
    is_limit_down: bool = False,
    volume: float = 1_000_000.0,
    open_: float = 10.0,
) -> PriceBar:
    return PriceBar(
        symbol=symbol,
        trade_date=date(2024, 6, 4),
        open=open_,
        high=open_ * 1.02,
        low=open_ * 0.98,
        close=open_,
        volume=volume,
        is_suspended=is_suspended,
        is_limit_up=is_limit_up,
        is_limit_down=is_limit_down,
    )


@pytest.mark.asyncio
async def test_limit_up_rejects_buy(broker: SimulatedBroker) -> None:
    broker.set_bars([_bar(is_limit_up=True)])
    ack = await broker.place_order(
        OrderRequest(
            client_order_id="t1",
            symbol="600000.SH",
            side="buy",
            quantity=100,
            order_type="market",
        )
    )
    assert ack.accepted is False
    assert ack.reject_reason == "limit_up_cannot_buy"
    assert broker.unfilled[-1].reason == "limit_up_cannot_buy"


@pytest.mark.asyncio
async def test_suspended_rejects(broker: SimulatedBroker) -> None:
    broker.set_bars([_bar(is_suspended=True)])
    ack = await broker.place_order(
        OrderRequest(
            client_order_id="t2",
            symbol="600000.SH",
            side="buy",
            quantity=100,
            order_type="market",
        )
    )
    assert ack.accepted is False
    assert ack.reject_reason == "suspended"


@pytest.mark.asyncio
async def test_t1_cannot_sell_same_day(broker: SimulatedBroker) -> None:
    broker.set_bars([_bar()])
    buy = await broker.place_order(
        OrderRequest(
            client_order_id="buy1",
            symbol="600000.SH",
            side="buy",
            quantity=1000,
            order_type="market",
        )
    )
    assert buy.accepted is True
    sell = await broker.place_order(
        OrderRequest(
            client_order_id="sell1",
            symbol="600000.SH",
            side="sell",
            quantity=1000,
            order_type="market",
        )
    )
    assert sell.accepted is False
    assert sell.reject_reason == "t1_not_sellable"

    broker.roll_day()
    sell2 = await broker.place_order(
        OrderRequest(
            client_order_id="sell2",
            symbol="600000.SH",
            side="sell",
            quantity=1000,
            order_type="market",
        )
    )
    assert sell2.accepted is True
    assert sell2.filled_qty == 1000


@pytest.mark.asyncio
async def test_fees_deducted_on_buy(broker: SimulatedBroker) -> None:
    broker.set_bars([_bar(open_=10.0)])
    before = (await broker.get_account()).cash
    ack = await broker.place_order(
        OrderRequest(
            client_order_id="fee1",
            symbol="600000.SH",
            side="buy",
            quantity=1000,
            order_type="market",
        )
    )
    assert ack.accepted is True
    after = (await broker.get_account()).cash
    notional = 1000 * float(ack.avg_price or 0)
    assert before - after == pytest.approx(notional + ack.fees)
    assert ack.fees >= 5.0


@pytest.mark.asyncio
async def test_idempotent_place_order(broker: SimulatedBroker) -> None:
    broker.set_bars([_bar()])
    req = OrderRequest(
        client_order_id="idem-1",
        symbol="600000.SH",
        side="buy",
        quantity=100,
        order_type="market",
    )
    a1 = await broker.place_order(req)
    a2 = await broker.place_order(req)
    assert a1.accepted is True
    assert a2.is_duplicate is True
    assert a2.broker_order_id == a1.broker_order_id
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 100


@pytest.mark.asyncio
async def test_guard_duplicate_flag() -> None:
    guard = InMemoryIdempotencyGuard()
    from quantagent.execution.broker.base import OrderAck

    async def place(_req: OrderRequest) -> OrderAck:
        return OrderAck(client_order_id="x", accepted=True, broker_order_id="B1")

    req = OrderRequest(client_order_id="x", symbol="A", side="buy", quantity=1, order_type="market")
    first = await guard.place_once(req, place)
    second = await guard.place_once(req, place)
    assert first.is_duplicate is False
    assert second.is_duplicate is True


def test_make_client_order_id_deterministic() -> None:
    a = make_client_order_id("20260603-cn-daily", "600519.SH", "buy", 1)
    b = make_client_order_id("20260603-cn-daily", "600519.SH", "buy", 1)
    assert a == b
    assert a == "20260603-cn-daily-600519SH-B-001"


def test_state_machine_valid_and_invalid() -> None:
    assert transition("proposed", "risk_approved") == "risk_approved"
    with pytest.raises(InvalidTransition):
        transition("filled", "submitted")
    with pytest.raises(InvalidTransition):
        transition("proposed", "filled")
