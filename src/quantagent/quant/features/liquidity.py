"""Liquidity and turnover factors."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import Factor, FactorInput, entity_col


class Turnover20d(Factor):
    """20-day average turnover rate (decimal ratio)."""

    code = "turnover_20d"
    name = "20-day average turnover"
    category = "liquidity"
    lookback_days = 20
    required_columns = ["turnover_rate"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        return prices.select(
            pl.col("turnover_rate").rolling_mean(window_size=20).over(ent).alias("_t")
        ).get_column("_t")


class TurnoverRatio5_60(Factor):
    """Short / long turnover ratio — attention shock proxy."""

    code = "turnover_ratio_5_60"
    name = "turnover 5d / 60d ratio"
    category = "liquidity"
    lookback_days = 60
    required_columns = ["turnover_rate"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        t5 = pl.col("turnover_rate").rolling_mean(window_size=5).over(ent)
        t60 = pl.col("turnover_rate").rolling_mean(window_size=60).over(ent)
        return prices.select((t5 / t60).alias("_r")).get_column("_r")


class AmihudIlliq20d(Factor):
    """Amihud illiquidity: mean(|ret| / amount) over 20 days."""

    code = "amihud_illiq_20d"
    name = "Amihud illiquidity 20d"
    category = "liquidity"
    lookback_days = 20
    required_columns = ["close", "amount"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret_abs = (pl.col("close") / pl.col("close").shift(1).over(ent) - 1.0).abs()
        amount = pl.col("amount").cast(pl.Float64)
        daily = pl.when(amount > 0).then(ret_abs / amount).otherwise(None)
        return prices.select(daily.rolling_mean(window_size=20).over(ent).alias("_a")).get_column(
            "_a"
        )
