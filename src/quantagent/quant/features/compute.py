"""Compute one or many factors into a wide panel."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import FactorInput, entity_col, sorted_prices
from quantagent.quant.features.registry import MVP_FACTOR_CODES, get_factor


def compute_factors(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
) -> pl.DataFrame:
    """Return sorted prices columns + one column per requested factor code."""
    prices = sorted_prices(data.prices)
    ent = entity_col(prices)
    out = prices.select([ent, "trade_date"])
    selected = list(codes) if codes is not None else list(MVP_FACTOR_CODES)
    for code in selected:
        factor = get_factor(code)
        # Re-bind prices so each factor sees the same sorted panel
        bound = FactorInput(
            prices=prices,
            financials=data.financials,
            valuations=data.valuations,
            money_flow=data.money_flow,
            events=data.events,
            industry=data.industry,
            as_of=data.as_of,
            meta=data.meta,
        )
        out = out.with_columns(factor.compute(bound))
    return out
