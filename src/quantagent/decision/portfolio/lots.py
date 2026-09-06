"""Lot rounding: buy size floored to min lot; residual stays cash."""

from __future__ import annotations

from quantagent.core.market import MarketConfig


def floor_to_lot(quantity: float, lot: int) -> float:
    if lot <= 0:
        raise ValueError("lot must be positive")
    if quantity <= 0:
        return 0.0
    return float((int(quantity) // lot) * lot)


def round_weights_to_lots(
    weights: dict[str, float],
    *,
    prices: dict[str, float],
    total_value: float,
    market: MarketConfig,
    boards: dict[str, str] | None = None,
) -> tuple[dict[str, float], float]:
    """Convert target weights to lot-rounded weights; return (weights, cash_weight).

    Residual notional after flooring becomes cash.
    """
    boards = boards or {}
    lot_weights: dict[str, float] = {}
    allocated = 0.0
    for symbol, w in weights.items():
        px = prices.get(symbol)
        if px is None or px <= 0 or total_value <= 0:
            continue
        board = boards.get(symbol, "main")
        lot = market.lot_size(board)
        target_notional = w * total_value
        raw_qty = target_notional / px
        qty = floor_to_lot(raw_qty, lot)
        if qty <= 0:
            continue
        notional = qty * px
        nw = notional / total_value
        lot_weights[symbol] = nw
        allocated += nw
    cash = max(0.0, 1.0 - allocated)
    return lot_weights, cash
