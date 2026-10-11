"""Volatility and higher-moment factors."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import Factor, FactorInput, entity_col


def _daily_ret_expr(ent: str) -> pl.Expr:
    return pl.col("close") / pl.col("close").shift(1).over(ent) - 1.0


class Vol20d(Factor):
    """20-day standard deviation of daily close-to-close returns."""

    code = "vol_20d"
    name = "20-day realized volatility"
    category = "volatility"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = _daily_ret_expr(ent)
        return prices.select(ret.rolling_std(window_size=20).over(ent).alias("_v")).get_column("_v")


class Vol60d(Factor):
    """60-day realized volatility."""

    code = "vol_60d"
    name = "60-day realized volatility"
    category = "volatility"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = _daily_ret_expr(ent)
        return prices.select(ret.rolling_std(window_size=60).over(ent).alias("_v")).get_column("_v")


class VolRatio20_60(Factor):
    """Short / long realized vol ratio."""

    code = "vol_ratio_20_60"
    name = "vol 20d / 60d ratio"
    category = "volatility"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = _daily_ret_expr(ent)
        v20 = ret.rolling_std(window_size=20).over(ent)
        v60 = ret.rolling_std(window_size=60).over(ent)
        return prices.select((v20 / v60).alias("_r")).get_column("_r")


class DownsideVol60d(Factor):
    """60d downside deviation: sqrt(mean(min(ret, 0)^2))."""

    code = "downside_vol_60d"
    name = "60d downside volatility"
    category = "volatility"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = _daily_ret_expr(ent)
        neg = pl.min_horizontal(ret, pl.lit(0.0))
        return prices.select(
            neg.pow(2).rolling_mean(window_size=60).over(ent).sqrt().alias("_d")
        ).get_column("_d")


class MaxDd60d(Factor):
    """60d drawdown from rolling peak: close / rolling_max - 1 (≤ 0)."""

    code = "max_dd_60d"
    name = "60d max drawdown"
    category = "volatility"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        peak = pl.col("close").rolling_max(window_size=60).over(ent)
        return prices.select((pl.col("close") / peak - 1.0).alias("_dd")).get_column("_dd")


class Skew60d(Factor):
    """60d skewness of daily returns."""

    code = "skew_60d"
    name = "60d return skewness"
    category = "volatility"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = _daily_ret_expr(ent)
        return prices.select(ret.rolling_skew(window_size=60).over(ent).alias("_s")).get_column(
            "_s"
        )


class Kurt60d(Factor):
    """60d kurtosis of daily returns."""

    code = "kurt_60d"
    name = "60d return kurtosis"
    category = "volatility"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ret = _daily_ret_expr(ent)
        return prices.select(
            ret.rolling_kurtosis(window_size=60).over(ent).alias("_k")
        ).get_column("_k")


class Beta252d(Factor):
    """252d beta vs equal-weight cross-section market return."""

    code = "beta_252d"
    name = "252d market beta"
    category = "volatility"
    lookback_days = 252
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        with_ret = prices.with_columns(_daily_ret_expr(ent).alias("_ret"))
        mkt = with_ret.group_by("trade_date", maintain_order=True).agg(
            pl.col("_ret").mean().alias("_mkt")
        )
        joined = with_ret.join(mkt, on="trade_date", how="left").sort([ent, "trade_date"])
        # Rolling cov(ret, mkt) / var(mkt) via rolling moments
        joined = joined.with_columns(
            [
                pl.col("_ret").rolling_mean(window_size=252).over(ent).alias("_ret_mu"),
                pl.col("_mkt").rolling_mean(window_size=252).over(ent).alias("_mkt_mu"),
            ]
        )
        joined = joined.with_columns(
            [
                (
                    (pl.col("_ret") * pl.col("_mkt")).rolling_mean(window_size=252).over(ent)
                    - pl.col("_ret_mu") * pl.col("_mkt_mu")
                ).alias("_cov"),
                (
                    (pl.col("_mkt") * pl.col("_mkt")).rolling_mean(window_size=252).over(ent)
                    - pl.col("_mkt_mu").pow(2)
                ).alias("_var_m"),
            ]
        )
        return joined.select(
            pl.when(pl.col("_var_m").abs() > 1e-15)
            .then(pl.col("_cov") / pl.col("_var_m"))
            .otherwise(None)
            .alias("_b")
        ).get_column("_b")
