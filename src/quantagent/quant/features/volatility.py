"""Volatility factors."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import Factor, FactorInput, entity_col


class Vol20d(Factor):
    """20-day standard deviation of daily close-to-close returns."""

    code = "vol_20d"
    name = "20-day realized volatility"
    category = "volatility"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = pl.col("close") / pl.col("close").shift(1).over(ent) - 1.0
        return prices.select(ret.rolling_std(window_size=20).over(ent).alias("_v")).get_column("_v")
