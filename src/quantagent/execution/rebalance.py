"""Equal-weight Top-N rebalance shared by shadow and backtest."""

from __future__ import annotations

from datetime import date

from quantagent.core.market import MarketConfig
from quantagent.decision.portfolio.lots import floor_to_lot
from quantagent.execution.broker.base import OrderAck, OrderRequest
from quantagent.execution.broker.simulated import SimulatedBroker
from quantagent.execution.orders.idempotency import make_client_order_id


async def rebalance_equal_weight(
    broker: SimulatedBroker,
    market: MarketConfig,
    symbols: list[str],
    *,
    as_of: date,
    run_id: str,
) -> list[OrderAck]:
    """Trade toward an equal weight on ``symbols`` at the current bars' open.

    Caller chooses the session. Shadow passes the signal day; the portfolio
    backtest passes the next session so the fill is that day's open.
    """
    if not symbols:
        return []
    equity = broker.mark_to_market()
    if equity <= 0:
        return []
    target_w = 1.0 / len(symbols)
    positions = {p.symbol: p for p in await broker.get_positions()}
    oid_run = f"{run_id}-{as_of.isoformat()}"
    acks: list[OrderAck] = []
    seq = 0
    lot = market.lot_size("main")
    for sym, pos in positions.items():
        if sym in symbols:
            continue
        sellable = pos.sellable_qty if pos.sellable_qty > 0 else 0.0
        if sellable <= 0:
            continue
        qty = floor_to_lot(sellable, lot) or sellable
        if pos.quantity <= market.min_lot_buy:
            qty = pos.quantity
        seq += 1
        acks.append(
            await broker.place_order(
                OrderRequest(
                    client_order_id=make_client_order_id(oid_run, sym, "sell", seq),
                    symbol=sym,
                    side="sell",
                    quantity=float(qty),
                )
            )
        )
    equity = broker.mark_to_market()
    positions = {p.symbol: p for p in await broker.get_positions()}
    for sym in symbols:
        bar = broker._bars.get(sym)  # noqa: SLF001 — same mark path as shadow
        if bar is None or bar.close <= 0:
            continue
        target_notional = target_w * equity
        current = positions.get(sym)
        current_notional = current.market_value if current else 0.0
        delta = target_notional - current_notional
        if abs(delta) < bar.close * lot * 0.5:
            continue
        if delta > 0:
            qty = floor_to_lot(delta / bar.close, lot)
            if qty <= 0:
                continue
            seq += 1
            acks.append(
                await broker.place_order(
                    OrderRequest(
                        client_order_id=make_client_order_id(oid_run, sym, "buy", seq),
                        symbol=sym,
                        side="buy",
                        quantity=float(qty),
                    )
                )
            )
        else:
            if current is None or current.sellable_qty <= 0:
                continue
            qty = floor_to_lot(abs(delta) / bar.close, lot)
            qty = min(qty, current.sellable_qty)
            if qty <= 0:
                continue
            seq += 1
            acks.append(
                await broker.place_order(
                    OrderRequest(
                        client_order_id=make_client_order_id(oid_run, sym, "sell", seq),
                        symbol=sym,
                        side="sell",
                        quantity=float(qty),
                    )
                )
            )
    return acks
