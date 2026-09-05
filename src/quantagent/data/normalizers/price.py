"""Normalize vendor daily price frames to the canonical OHLCV schema.

Canonical columns (pre-Loader)::

    symbol, trade_date, open, high, low, close, prev_close,
    volume, amount, turnover_rate, source

Units:
- prices / amount: 元
- volume: 股
- turnover_rate: decimal ratio (0.015 = 1.5%)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.errors import DataError

CANONICAL_PRICE_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "amount",
    "turnover_rate",
    "source",
]


class PriceNormalizer:
    """Map akshare / baostock raw frames → canonical price_daily columns."""

    def normalize(self, batch: RawBatch, df: pl.DataFrame | None = None) -> pl.DataFrame:
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        if batch.source == "akshare":
            return self._normalize_akshare(frame, batch)
        if batch.source == "baostock":
            return self._normalize_baostock(frame, batch)
        raise DataError(f"No price normalizer for source={batch.source!r}")

    def normalize_from_archive(self, raw_path: Path) -> pl.DataFrame:
        df, batch = load_raw_batch(raw_path)
        return self.normalize(batch, df)

    def _normalize_akshare(self, df: pl.DataFrame, batch: RawBatch) -> pl.DataFrame:
        """akshare ``stock_zh_a_hist``: volume=手, amount=元, 换手率=%."""
        cols = set(df.columns)
        required = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"}
        missing = required - cols
        if missing:
            raise DataError(f"akshare price frame missing columns: {sorted(missing)}")

        symbol_expr = self._akshare_symbol_expr(df, batch)
        out = df.select(
            symbol_expr.alias("symbol"),
            pl.col("日期").cast(pl.Date).alias("trade_date"),
            pl.col("开盘").cast(pl.Float64).alias("open"),
            pl.col("最高").cast(pl.Float64).alias("high"),
            pl.col("最低").cast(pl.Float64).alias("low"),
            pl.col("收盘").cast(pl.Float64).alias("close"),
            pl.lit(None).cast(pl.Float64).alias("prev_close"),
            (pl.col("成交量").cast(pl.Float64) * 100).cast(pl.Int64).alias("volume"),
            pl.col("成交额").cast(pl.Float64).alias("amount"),
            (
                (pl.col("换手率").cast(pl.Float64) / 100.0)
                if "换手率" in cols
                else pl.lit(None).cast(pl.Float64)
            ).alias("turnover_rate"),
            pl.lit(batch.source).alias("source"),
        )
        return out.select(CANONICAL_PRICE_COLUMNS)

    def _akshare_symbol_expr(self, df: pl.DataFrame, batch: RawBatch) -> pl.Expr:
        if "_request_symbol" in df.columns:
            return (
                pl.col("_request_symbol")
                .cast(pl.Utf8)
                .map_elements(
                    lambda s: normalize_symbol(str(s), market="CN"),
                    return_dtype=pl.Utf8,
                )
            )
        if "股票代码" in df.columns:
            return (
                pl.col("股票代码")
                .cast(pl.Utf8)
                .map_elements(
                    lambda s: normalize_symbol(str(s), market="CN"),
                    return_dtype=pl.Utf8,
                )
            )
        symbols = batch.meta.get("symbols") or []
        if len(symbols) == 1:
            return pl.lit(normalize_symbol(str(symbols[0]), market="CN"))
        raise DataError("akshare archive missing symbol column and meta.symbols")

    def _normalize_baostock(self, df: pl.DataFrame, batch: RawBatch) -> pl.DataFrame:
        """baostock fields are strings; volume already in 股, turn in %."""
        cols = set(df.columns)
        required = {"date", "code", "open", "high", "low", "close", "volume", "amount"}
        missing = required - cols
        if missing:
            raise DataError(f"baostock price frame missing columns: {sorted(missing)}")

        def _code_to_symbol(code: str) -> str:
            # baostock: sh.600519
            parts = str(code).split(".")
            if len(parts) == 2:
                return normalize_symbol(f"{parts[1]}.{parts[0]}", market="CN")
            return normalize_symbol(code, market="CN")

        turn_expr = (
            (pl.col("turn").cast(pl.Float64, strict=False) / 100.0)
            if "turn" in cols
            else pl.lit(None).cast(pl.Float64)
        )
        prev_expr = (
            pl.col("preclose").cast(pl.Float64, strict=False)
            if "preclose" in cols
            else pl.lit(None).cast(pl.Float64)
        )

        out = df.select(
            pl.col("code")
            .cast(pl.Utf8)
            .map_elements(_code_to_symbol, return_dtype=pl.Utf8)
            .alias("symbol"),
            pl.col("date").str.to_date().alias("trade_date"),
            pl.col("open").cast(pl.Float64, strict=False).alias("open"),
            pl.col("high").cast(pl.Float64, strict=False).alias("high"),
            pl.col("low").cast(pl.Float64, strict=False).alias("low"),
            pl.col("close").cast(pl.Float64, strict=False).alias("close"),
            prev_expr.alias("prev_close"),
            pl.col("volume").cast(pl.Int64, strict=False).alias("volume"),
            pl.col("amount").cast(pl.Float64, strict=False).alias("amount"),
            turn_expr.alias("turnover_rate"),
            pl.lit(batch.source).alias("source"),
        )
        # Drop empty-string rows baostock sometimes emits
        out = out.filter(pl.col("close").is_not_null())
        return out.select(CANONICAL_PRICE_COLUMNS)
