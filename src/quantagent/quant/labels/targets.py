"""Forward-return labels for factor evaluation.

Labels are pure transforms on price panels. Callers must ensure prices are
Point-in-Time safe; this module never queries the database.
"""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import entity_col, require_columns, sorted_prices
from quantagent.shared.errors import QuantAgentError


class LabelError(QuantAgentError):
    """Invalid label construction input."""


def forward_return_col(horizon: int) -> str:
    if horizon < 1:
        raise LabelError(f"horizon must be >= 1, got {horizon}")
    return f"fwd_ret_{horizon}d"


def attach_forward_returns(
    prices: pl.DataFrame,
    *,
    horizons: list[int] | tuple[int, ...] = (1, 5, 20),
    price_col: str = "close",
) -> pl.DataFrame:
    """Append ``fwd_ret_{h}d`` = close_{t+h} / close_t - 1 for each horizon.

    Value at row ``t`` uses future prices and is therefore a *label*, not a
    feature. Evaluation must align factor at ``t`` with this label at ``t``.
    """
    if not horizons:
        raise LabelError("horizons must be non-empty")
    prices = sorted_prices(prices)
    ent = entity_col(prices)
    require_columns(prices, [price_col], context="attach_forward_returns")

    out = prices
    for h in horizons:
        if h < 1:
            raise LabelError(f"horizon must be >= 1, got {h}")
        col = forward_return_col(h)
        out = out.with_columns(
            (pl.col(price_col).shift(-h).over(ent) / pl.col(price_col) - 1.0).alias(col)
        )
    return out
