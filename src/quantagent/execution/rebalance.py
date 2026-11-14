"""Equal-weight Top-N rebalance shared by shadow and backtest."""

from __future__ import annotations

from datetime import date

from quantagent.core.market import MarketConfig
from quantagent.decision.portfolio.lots import floor_to_lot
from quantagent.decision.portfolio.turnover import limit_turnover
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
    max_turnover: float | None = None,
) -> list[OrderAck]:
    """Trade toward an equal weight on ``symbols`` at the current bars' open.

    Caller chooses the session. Shadow passes the signal day; the portfolio
    backtest passes the next session so the fill is that day's open.

    ``max_turnover`` is one-way (½ Σ|Δw|). ``None`` loads
    ``config/portfolio/*.yaml`` ``rebalance.max_turnover_per_rebalance``.
    """
    if not symbols:
        return []
    equity = broker.mark_to_market()
    if equity <= 0:
        return []

    cap = _resolve_max_turnover(max_turnover)
    positions = {p.symbol: p for p in await broker.get_positions()}
    current_w = {
        sym: pos.market_value / equity
        for sym, pos in positions.items()
        if pos.market_value > 0 and equity > 0
    }
    target_w = {sym: 1.0 / len(symbols) for sym in symbols}
    limited = limit_turnover(target_w, current_w, cap)

    oid_run = f"{run_id}-{as_of.isoformat()}"
    acks: list[OrderAck] = []
    seq = 0
    lot = market.lot_size("main")

    # Sells first (exits and reduces), then buys — matches turnover priority.
    sell_syms = sorted(
        {s for s in set(current_w) | set(limited) if limited.get(s, 0.0) < current_w.get(s, 0.0)},
        key=lambda s: current_w.get(s, 0.0) - limited.get(s, 0.0),
        reverse=True,
    )
    for sym in sell_syms:
        pos = positions.get(sym)
        if pos is None or pos.sellable_qty <= 0:
            continue
        bar = broker._bars.get(sym)  # noqa: SLF001 — same mark path as shadow
        if bar is None or bar.close <= 0:
            continue
        target_notional = limited.get(sym, 0.0) * equity
        delta = target_notional - pos.market_value
        if delta >= -bar.close * lot * 0.5:
            continue
        qty = floor_to_lot(abs(delta) / bar.close, lot)
        qty = min(qty, pos.sellable_qty)
        if pos.quantity <= market.min_lot_buy and limited.get(sym, 0.0) <= 1e-15:
            qty = pos.sellable_qty if pos.sellable_qty > 0 else pos.quantity
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

    equity = broker.mark_to_market()
    positions = {p.symbol: p for p in await broker.get_positions()}
    buy_syms = sorted(
        {s for s in limited if limited[s] > current_w.get(s, 0.0)},
        key=lambda s: limited[s] - current_w.get(s, 0.0),
        reverse=True,
    )
    for sym in buy_syms:
        bar = broker._bars.get(sym)  # noqa: SLF001
        if bar is None or bar.close <= 0:
            continue
        target_notional = limited[sym] * equity
        current = positions.get(sym)
        current_notional = current.market_value if current else 0.0
        delta = target_notional - current_notional
        if delta < bar.close * lot * 0.5:
            continue
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
    return acks


def _resolve_max_turnover(max_turnover: float | None) -> float:
    if max_turnover is not None:
        return float(max_turnover)
    from quantagent.decision.portfolio.config import load_portfolio_config

    return float(load_portfolio_config("CN").rebalance.max_turnover_per_rebalance)
