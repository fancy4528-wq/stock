"""Normalize vendor valuation frames → canonical ``valuation_daily`` schema."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.errors import DataError

CANONICAL_VALUATION_COLUMNS = [
    "symbol",
    "trade_date",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "pe_lyr",
    "market_cap",
    "circ_market_cap",
    "dividend_yield",
    "source",
]


class ValuationNormalizer:
    """Map baostock peTTM/pbMRQ/psTTM rows → canonical columns."""

    def normalize(self, batch: RawBatch, df: pl.DataFrame | None = None) -> pl.DataFrame:
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        if batch.source == "baostock":
            return self._normalize_baostock(frame, batch)
        raise DataError(f"No valuation normalizer for source={batch.source!r}")

    def normalize_from_archive(self, raw_path: Path) -> pl.DataFrame:
        df, batch = load_raw_batch(raw_path)
        return self.normalize(batch, df)

    def _normalize_baostock(self, df: pl.DataFrame, batch: RawBatch) -> pl.DataFrame:
        cols = set(df.columns)
        required = {"date", "code", "peTTM", "pbMRQ", "psTTM"}
        missing = required - cols
        if missing:
            raise DataError(f"baostock valuation frame missing columns: {sorted(missing)}")

        def _code_to_symbol(code: str) -> str:
            parts = str(code).split(".")
            if len(parts) == 2:
                return normalize_symbol(f"{parts[1]}.{parts[0]}", market="CN")
            return normalize_symbol(code, market="CN")

        out = df.select(
            pl.col("code")
            .cast(pl.Utf8)
            .map_elements(_code_to_symbol, return_dtype=pl.Utf8)
            .alias("symbol"),
            pl.col("date").str.to_date().alias("trade_date"),
            pl.col("peTTM").cast(pl.Float64, strict=False).alias("pe_ttm"),
            pl.col("pbMRQ").cast(pl.Float64, strict=False).alias("pb"),
            pl.col("psTTM").cast(pl.Float64, strict=False).alias("ps_ttm"),
            pl.lit(None).cast(pl.Float64).alias("pe_lyr"),
            pl.lit(None).cast(pl.Float64).alias("market_cap"),
            pl.lit(None).cast(pl.Float64).alias("circ_market_cap"),
            pl.lit(None).cast(pl.Float64).alias("dividend_yield"),
            pl.lit(batch.source).alias("source"),
        )
        # Keep rows with at least one usable multiple.
        out = out.filter(
            pl.col("trade_date").is_not_null()
            & (
                pl.col("pe_ttm").is_not_null()
                | pl.col("pb").is_not_null()
                | pl.col("ps_ttm").is_not_null()
            )
        )
        return out.select(CANONICAL_VALUATION_COLUMNS).sort(["symbol", "trade_date"])
