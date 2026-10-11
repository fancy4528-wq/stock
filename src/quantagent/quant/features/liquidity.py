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


class Amount20d(Factor):
    """20-day average yuan amount."""

    code = "amount_20d"
    name = "20-day average amount"
    category = "liquidity"
    lookback_days = 20
    required_columns = ["amount"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        return prices.select(
            pl.col("amount").cast(pl.Float64).rolling_mean(window_size=20).over(ent).alias("_a")
        ).get_column("_a")


class VolumeTrend20d(Factor):
    """Volume attention: 5d mean volume / 20d mean volume."""

    code = "volume_trend_20d"
    name = "volume 5d / 20d trend"
    category = "liquidity"
    lookback_days = 20
    required_columns = ["volume"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        v = pl.col("volume").cast(pl.Float64)
        v5 = v.rolling_mean(window_size=5).over(ent)
        v20 = v.rolling_mean(window_size=20).over(ent)
        return prices.select((v5 / v20).alias("_vt")).get_column("_vt")


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


class VolPriceCorr20d(Factor):
    """20d correlation between daily return and volume."""

    code = "vol_price_corr_20d"
    name = "volume-price correlation 20d"
    category = "liquidity"
    lookback_days = 20
    required_columns = ["close", "volume"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        # rolling_corr is not group-aware via .over; compute per entity
        frames: list[pl.DataFrame] = []
        for key, group in prices.sort([ent, "trade_date"]).group_by(ent, maintain_order=True):
            entity_key = key[0] if isinstance(key, tuple) else key
            g = group.with_columns(
                (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("_ret"),
                pl.col("volume").cast(pl.Float64).alias("_vol"),
            )
            corr = g.select(
                pl.rolling_corr(pl.col("_ret"), pl.col("_vol"), window_size=20).alias("_c")
            ).get_column("_c")
            frames.append(
                pl.DataFrame(
                    {
                        ent: [entity_key] * g.height,
                        "trade_date": g.get_column("trade_date"),
                        "_c": corr,
                    }
                )
            )
        if not frames:
            return pl.Series("_c", [None] * prices.height, dtype=pl.Float64)
        out = pl.concat(frames)
        aligned = prices.select([ent, "trade_date"]).join(
            out, on=[ent, "trade_date"], how="left"
        )
        return aligned.get_column("_c")
