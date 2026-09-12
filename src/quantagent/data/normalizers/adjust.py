"""Normalize vendor adjust-factor frames → canonical ``adjust_factor`` schema."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.errors import DataError

CN_TZ = ZoneInfo("Asia/Shanghai")

CANONICAL_ADJUST_COLUMNS = [
    "symbol",
    "trade_date",
    "factor_qfq",
    "factor_hfq",
    "announced_at",
    "source",
]


def trade_date_eod(trade_date: date) -> datetime:
    """Map ex-div / trade calendar date to A-share session close (15:00 Asia/Shanghai)."""
    return datetime.combine(trade_date, time(15, 0), tzinfo=CN_TZ)


class AdjustNormalizer:
    """Map baostock ``query_adjust_factor`` rows → canonical columns."""

    def normalize(self, batch: RawBatch, df: pl.DataFrame | None = None) -> pl.DataFrame:
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        if batch.source == "baostock":
            return self._normalize_baostock(frame, batch)
        raise DataError(f"No adjust normalizer for source={batch.source!r}")

    def normalize_from_archive(self, raw_path: Path) -> pl.DataFrame:
        df, batch = load_raw_batch(raw_path)
        return self.normalize(batch, df)

    def _normalize_baostock(self, df: pl.DataFrame, batch: RawBatch) -> pl.DataFrame:
        cols = set(df.columns)
        required = {"code", "dividOperateDate", "foreAdjustFactor", "backAdjustFactor"}
        missing = required - cols
        if missing:
            raise DataError(f"baostock adjust frame missing columns: {sorted(missing)}")

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
            pl.col("dividOperateDate").str.to_date().alias("trade_date"),
            pl.col("foreAdjustFactor").cast(pl.Float64, strict=False).alias("factor_qfq"),
            pl.col("backAdjustFactor").cast(pl.Float64, strict=False).alias("factor_hfq"),
            pl.lit(batch.source).alias("source"),
        )
        out = out.filter(
            pl.col("trade_date").is_not_null()
            & pl.col("factor_qfq").is_not_null()
            & pl.col("factor_hfq").is_not_null()
        )
        rows = out.to_dicts()
        enriched: list[dict[str, object]] = []
        for row in rows:
            td = row["trade_date"]
            if not isinstance(td, date):
                td = date.fromisoformat(str(td))
            enriched.append(
                {
                    "symbol": row["symbol"],
                    "trade_date": td,
                    "factor_qfq": row["factor_qfq"],
                    "factor_hfq": row["factor_hfq"],
                    "announced_at": trade_date_eod(td),
                    "source": row["source"],
                }
            )
        if not enriched:
            return pl.DataFrame({c: [] for c in CANONICAL_ADJUST_COLUMNS})
        return pl.DataFrame(enriched).select(CANONICAL_ADJUST_COLUMNS)
