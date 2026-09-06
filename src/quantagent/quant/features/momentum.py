"""Momentum and short-term reversal factors."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import Factor, FactorInput, entity_col


def _total_return(prices: pl.DataFrame, window: int) -> pl.Series:
    ent = entity_col(prices)
    return prices.select(
        (pl.col("close") / pl.col("close").shift(window).over(ent) - 1.0).alias("_r")
    ).get_column("_r")


class Mom20d(Factor):
    code = "mom_20d"
    name = "20-day momentum"
    category = "momentum"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return _total_return(prices, 20)


class Mom60d(Factor):
    code = "mom_60d"
    name = "60-day momentum"
    category = "momentum"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return _total_return(prices, 60)


class Rev5d(Factor):
    """Negative of the prior 5-day return (A-share short-term reversal)."""

    code = "rev_5d"
    name = "5-day reversal"
    category = "reversal"
    lookback_days = 5
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return (-_total_return(prices, 5)).alias("rev_5d")
