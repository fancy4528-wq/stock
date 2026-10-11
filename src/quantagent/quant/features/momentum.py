"""Momentum and trend factors."""

from __future__ import annotations

import numpy as np
import polars as pl

from quantagent.quant.features.base import Factor, FactorInput, entity_col


def total_return(prices: pl.DataFrame, window: int) -> pl.Series:
    """Close-to-close total return over ``window`` sessions."""
    ent = entity_col(prices)
    return prices.select(
        (pl.col("close") / pl.col("close").shift(window).over(ent) - 1.0).alias("_r")
    ).get_column("_r")


def _ols_slope(window: pl.Series) -> float | None:
    raw = window.to_numpy().astype(np.float64)
    if raw.size < 3 or not np.all(np.isfinite(raw)) or abs(raw[0]) < 1e-15:
        return None
    # Normalize to first observation to avoid overflow on long price paths.
    y = raw / raw[0]
    x = np.arange(y.size, dtype=np.float64)
    x -= x.mean()
    y_c = y - y.mean()
    var_x = float((x * x).sum())
    if var_x < 1e-15:
        return None
    slope = float((x * y_c).sum() / var_x)
    mean_y = float(y.mean())
    if abs(mean_y) < 1e-15:
        return None
    return slope / mean_y


def _ols_r2(window: pl.Series) -> float | None:
    raw = window.to_numpy().astype(np.float64)
    if raw.size < 3 or not np.all(np.isfinite(raw)) or abs(raw[0]) < 1e-15:
        return None
    y = raw / raw[0]
    x = np.arange(y.size, dtype=np.float64)
    x -= x.mean()
    y_c = y - y.mean()
    var_x = float((x * x).sum())
    ss_tot = float((y_c * y_c).sum())
    if var_x < 1e-15 or ss_tot < 1e-15:
        return None
    slope = float((x * y_c).sum() / var_x)
    resid = y_c - slope * x
    ss_res = float((resid * resid).sum())
    return 1.0 - ss_res / ss_tot


class Mom5d(Factor):
    code = "mom_5d"
    name = "5-day momentum"
    category = "momentum"
    lookback_days = 5
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return total_return(prices, 5)


class Mom20d(Factor):
    code = "mom_20d"
    name = "20-day momentum"
    category = "momentum"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return total_return(prices, 20)


class Mom60d(Factor):
    code = "mom_60d"
    name = "60-day momentum"
    category = "momentum"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return total_return(prices, 60)


class Mom120d(Factor):
    code = "mom_120d"
    name = "120-day momentum"
    category = "momentum"
    lookback_days = 120
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        return total_return(prices, 120)


class Mom20dEx1w(Factor):
    """20-day momentum excluding the most recent 5 sessions."""

    code = "mom_20d_ex1w"
    name = "20d momentum ex last week"
    category = "momentum"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        return prices.select(
            (pl.col("close").shift(5).over(ent) / pl.col("close").shift(20).over(ent) - 1.0).alias(
                "_r"
            )
        ).get_column("_r")


class DistFromHigh252d(Factor):
    """Distance from 252-session high: close / rolling_max - 1."""

    code = "dist_from_high_252d"
    name = "distance from 252d high"
    category = "momentum"
    lookback_days = 252
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        hi = pl.col("close").rolling_max(window_size=252).over(ent)
        return prices.select((pl.col("close") / hi - 1.0).alias("_d")).get_column("_d")


class DistFromLow252d(Factor):
    """Distance from 252-session low: close / rolling_min - 1."""

    code = "dist_from_low_252d"
    name = "distance from 252d low"
    category = "momentum"
    lookback_days = 252
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        lo = pl.col("close").rolling_min(window_size=252).over(ent)
        return prices.select((pl.col("close") / lo - 1.0).alias("_d")).get_column("_d")


class MaCross5_20(Factor):
    """5d MA / 20d MA - 1."""

    code = "ma_cross_5_20"
    name = "MA 5/20 cross"
    category = "momentum"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        ma5 = pl.col("close").rolling_mean(window_size=5).over(ent)
        ma20 = pl.col("close").rolling_mean(window_size=20).over(ent)
        return prices.select((ma5 / ma20 - 1.0).alias("_m")).get_column("_m")


class TrendSlope60d(Factor):
    """60d OLS slope of close on time, divided by mean close."""

    code = "trend_slope_60d"
    name = "60d trend slope (standardized)"
    category = "momentum"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        return prices.select(
            pl.col("close").rolling_map(_ols_slope, window_size=60).over(ent).alias("_s")
        ).get_column("_s")


class TrendR260d(Factor):
    """R² of the 60d close-vs-time regression (trend quality)."""

    code = "trend_r2_60d"
    name = "60d trend R²"
    category = "momentum"
    lookback_days = 60
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        return prices.select(
            pl.col("close").rolling_map(_ols_r2, window_size=60).over(ent).alias("_r")
        ).get_column("_r")


class RelStrMarket(Factor):
    """20d stock return minus equal-weight market 20d return."""

    code = "rel_str_market"
    name = "relative strength vs market 20d"
    category = "momentum"
    lookback_days = 20
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        with_ret = prices.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over(ent) - 1.0).alias("_ret")
        )
        mkt = with_ret.group_by("trade_date", maintain_order=True).agg(
            pl.col("_ret").mean().alias("_mkt")
        )
        mkt = mkt.sort("trade_date").with_columns(
            ((1.0 + pl.col("_mkt")).log().rolling_sum(window_size=20).exp() - 1.0).alias(
                "_mkt_mom20"
            )
        )
        stock_mom = total_return(prices, 20)
        joined = prices.select([ent, "trade_date"]).with_columns(stock_mom.alias("_stock_mom"))
        joined = joined.join(mkt.select(["trade_date", "_mkt_mom20"]), on="trade_date", how="left")
        return joined.select((pl.col("_stock_mom") - pl.col("_mkt_mom20")).alias("_rs")).get_column(
            "_rs"
        )
