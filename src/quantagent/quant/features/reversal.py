"""Short-term reversal and lottery-style factors (A-share focus)."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import Factor, FactorInput, entity_col
from quantagent.quant.features.momentum import total_return


class Rev1d(Factor):
    """Negative of the prior 1-day return."""

    code = "rev_1d"
    name = "1-day reversal"
    category = "reversal"
    lookback_days = 1
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return (-total_return(prices, 1)).alias(self.code)


class Rev5d(Factor):
    """Negative of the prior 5-day return (A-share short-term reversal)."""

    code = "rev_5d"
    name = "5-day reversal"
    category = "reversal"
    lookback_days = 5
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return (-total_return(prices, 5)).alias(self.code)


class RevOvernight(Factor):
    """Overnight return: open / previous close - 1."""

    code = "rev_overnight"
    name = "overnight return"
    category = "reversal"
    lookback_days = 1
    required_columns = ["open", "close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        prev_close = pl.col("close").shift(1).over(ent)
        return prices.select(
            (pl.col("open") / prev_close - 1.0).alias("_r")
        ).get_column("_r")


class RevIntraday(Factor):
    """Intraday return: close / open - 1."""

    code = "rev_intraday"
    name = "intraday return"
    category = "reversal"
    lookback_days = 0
    required_columns = ["open", "close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return prices.select(
            (pl.col("close") / pl.col("open") - 1.0).alias("_r")
        ).get_column("_r")


class MaxRet20d(Factor):
    """Maximum single-day return over the prior 20 sessions (lottery proxy)."""

    code = "max_ret_20d"
    name = "20d max daily return"
    category = "reversal"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = pl.col("close") / pl.col("close").shift(1).over(ent) - 1.0
        return prices.select(ret.rolling_max(window_size=20).over(ent).alias("_m")).get_column(
            "_m"
        )
