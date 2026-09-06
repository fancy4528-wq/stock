"""Normalize vendor daily price frames to the canonical OHLCV schema.

Canonical columns (pre-Loader)::

    symbol, trade_date, open, high, low, close, prev_close,
    volume, amount, turnover_rate, source,
    limit_up_px, limit_down_px, is_limit_up, is_limit_down, is_suspended

Units:
- prices / amount: 元
- volume: 股
- turnover_rate: decimal ratio (0.015 = 1.5%)

Limit / suspend flags (Gate 1 A2):
- ``is_suspended`` from baostock ``tradestatus`` or volume==0 heuristic
- ``limit_*_px`` / ``is_limit_*`` from ``MarketConfig.price_limit`` + board (+ isST)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import polars as pl

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol, to_raw_digits
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
    "limit_up_px",
    "limit_down_px",
    "is_limit_up",
    "is_limit_down",
    "is_suspended",
]

_LIMIT_EPS = 1e-6
_TICK = Decimal("0.01")


def infer_board(symbol: str) -> str:
    """Map a CN symbol to board code used by ``config/markets/cn.yaml``."""
    digits = to_raw_digits(symbol)
    if digits.startswith("68"):
        return "star"
    if digits.startswith("30"):
        return "gem"
    if digits.startswith(("43", "83", "87", "88", "92")):
        return "bse"
    return "main"


def round_limit_price(raw: float) -> float:
    """Round limit prices to the A-share display tick (0.01, half-up)."""
    return float(Decimal(str(raw)).quantize(_TICK, rounding=ROUND_HALF_UP))


class PriceNormalizer:
    """Map akshare / baostock raw frames → canonical price_daily columns."""

    def __init__(self, market: MarketConfig | None = None) -> None:
        self._market = market or load_market_config("CN")

    def normalize(self, batch: RawBatch, df: pl.DataFrame | None = None) -> pl.DataFrame:
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        if batch.source == "akshare":
            if batch.meta.get("kind") == "index" or (
                "date" in frame.columns
                and "开盘" not in frame.columns
                and "code" not in frame.columns
            ):
                out = self._normalize_akshare_index(frame, batch)
                return self._with_empty_limit_flags(out)
            out = self._normalize_akshare(frame, batch)
            return self._enrich_limits(out, is_st_col="_is_st")
        if batch.source == "baostock":
            out = self._normalize_baostock(frame, batch)
            return self._enrich_limits(out, is_st_col="_is_st")
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
        prev_expr = self._akshare_prev_close_expr(df, cols)
        out = df.select(
            symbol_expr.alias("symbol"),
            pl.col("日期").cast(pl.Date).alias("trade_date"),
            pl.col("开盘").cast(pl.Float64).alias("open"),
            pl.col("最高").cast(pl.Float64).alias("high"),
            pl.col("最低").cast(pl.Float64).alias("low"),
            pl.col("收盘").cast(pl.Float64).alias("close"),
            prev_expr.alias("prev_close"),
            (pl.col("成交量").cast(pl.Float64) * 100).cast(pl.Int64).alias("volume"),
            pl.col("成交额").cast(pl.Float64).alias("amount"),
            (
                (pl.col("换手率").cast(pl.Float64) / 100.0)
                if "换手率" in cols
                else pl.lit(None).cast(pl.Float64)
            ).alias("turnover_rate"),
            pl.lit(batch.source).alias("source"),
            pl.lit(False).alias("_is_st"),
        )
        # Fill prev_close from prior close within the batch when vendor pct missing.
        out = out.sort(["symbol", "trade_date"]).with_columns(
            pl.when(pl.col("prev_close").is_null())
            .then(pl.col("close").shift(1).over("symbol"))
            .otherwise(pl.col("prev_close"))
            .alias("prev_close")
        )
        out = out.with_columns(
            ((pl.col("volume") == 0) | (pl.col("amount").fill_null(0) == 0)).alias(
                "is_suspended"
            )
        )
        return out

    def _akshare_prev_close_expr(self, df: pl.DataFrame, cols: set[str]) -> pl.Expr:
        """Derive prev_close from 涨跌幅 / 涨跌额 when present (single-day windows)."""
        if "涨跌幅" in cols:
            pct = pl.col("涨跌幅").cast(pl.Float64, strict=False) / 100.0
            return pl.when((pct.is_not_null()) & (pct != -1.0)).then(
                pl.col("收盘").cast(pl.Float64) / (1.0 + pct)
            ).otherwise(pl.lit(None).cast(pl.Float64))
        if "涨跌额" in cols:
            chg = pl.col("涨跌额").cast(pl.Float64, strict=False)
            return pl.when(chg.is_not_null()).then(
                pl.col("收盘").cast(pl.Float64) - chg
            ).otherwise(pl.lit(None).cast(pl.Float64))
        return pl.lit(None).cast(pl.Float64)

    def _normalize_akshare_index(self, df: pl.DataFrame, batch: RawBatch) -> pl.DataFrame:
        """akshare ``stock_zh_index_daily``: date/open/high/low/close/volume (股)."""
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise DataError(f"akshare index frame missing columns: {sorted(missing)}")

        symbol_expr = self._akshare_symbol_expr(df, batch)
        date_col = pl.col("date")
        if df.schema.get("date") == pl.Utf8:
            date_expr = date_col.str.to_date()
        else:
            date_expr = date_col.cast(pl.Date)

        out = df.select(
            symbol_expr.alias("symbol"),
            date_expr.alias("trade_date"),
            pl.col("open").cast(pl.Float64).alias("open"),
            pl.col("high").cast(pl.Float64).alias("high"),
            pl.col("low").cast(pl.Float64).alias("low"),
            pl.col("close").cast(pl.Float64).alias("close"),
            pl.lit(None).cast(pl.Float64).alias("prev_close"),
            pl.col("volume").cast(pl.Int64).alias("volume"),
            pl.lit(None).cast(pl.Float64).alias("amount"),
            pl.lit(None).cast(pl.Float64).alias("turnover_rate"),
            pl.lit(batch.source).alias("source"),
        )
        out = out.sort(["symbol", "trade_date"]).with_columns(
            pl.col("close").shift(1).over("symbol").alias("prev_close")
        )
        return out

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
        if "tradestatus" in cols:
            suspended_expr = (
                pl.col("tradestatus").cast(pl.Utf8).str.strip_chars().is_in(["0", "0.0"])
            )
        else:
            suspended_expr = pl.col("volume").cast(pl.Int64, strict=False).fill_null(0) == 0

        if "isST" in cols:
            st_expr = pl.col("isST").cast(pl.Utf8).str.strip_chars().is_in(["1", "1.0"])
        else:
            st_expr = pl.lit(False)

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
            suspended_expr.alias("is_suspended"),
            st_expr.alias("_is_st"),
        )
        # Drop empty-string rows baostock sometimes emits
        out = out.filter(pl.col("close").is_not_null())
        return out

    def _with_empty_limit_flags(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            pl.lit(None).cast(pl.Float64).alias("limit_up_px"),
            pl.lit(None).cast(pl.Float64).alias("limit_down_px"),
            pl.lit(False).alias("is_limit_up"),
            pl.lit(False).alias("is_limit_down"),
            pl.lit(False).alias("is_suspended"),
        ).select(CANONICAL_PRICE_COLUMNS)

    def _enrich_limits(self, df: pl.DataFrame, *, is_st_col: str) -> pl.DataFrame:
        """Attach limit prices + sealed-at-close flags from MarketConfig."""
        if df.is_empty():
            return pl.DataFrame({c: [] for c in CANONICAL_PRICE_COLUMNS})

        rows = df.to_dicts()
        enriched: list[dict[str, object]] = []
        for row in rows:
            symbol = str(row["symbol"])
            board = infer_board(symbol)
            is_st = bool(row.get(is_st_col) or False)
            suspended = bool(row.get("is_suspended") or False)
            prev = row.get("prev_close")
            close = row.get("close")

            limit_up_px: float | None = None
            limit_down_px: float | None = None
            is_limit_up = False
            is_limit_down = False

            if (
                not suspended
                and prev is not None
                and float(prev) > 0
                and close is not None
            ):
                up_ratio, down_ratio = self._market.price_limits(board=board, is_st=is_st)
                if up_ratio is not None:
                    limit_up_px = round_limit_price(float(prev) * (1.0 + up_ratio))
                    is_limit_up = float(close) + _LIMIT_EPS >= limit_up_px
                if down_ratio is not None:
                    limit_down_px = round_limit_price(float(prev) * (1.0 + down_ratio))
                    is_limit_down = float(close) - _LIMIT_EPS <= limit_down_px

            enriched.append(
                {
                    "symbol": symbol,
                    "trade_date": row["trade_date"],
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": close,
                    "prev_close": prev,
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                    "turnover_rate": row.get("turnover_rate"),
                    "source": row.get("source"),
                    "limit_up_px": limit_up_px,
                    "limit_down_px": limit_down_px,
                    "is_limit_up": is_limit_up,
                    "is_limit_down": is_limit_down,
                    "is_suspended": suspended,
                }
            )
        return pl.DataFrame(enriched).select(CANONICAL_PRICE_COLUMNS)
