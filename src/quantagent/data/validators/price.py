"""Price daily validation rules (subset of docs/04-data-sources.md §3.2)."""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from quantagent.data.validators.report import RuleResult

RuleFn = Callable[[pl.DataFrame], RuleResult]


def _row_key(symbol: str, trade_date: object) -> str:
    return f"{symbol}|{trade_date}"


def rule_px_001_ohlc(df: pl.DataFrame) -> RuleResult:
    """high >= low; high >= open/close; low <= open/close."""
    bad = df.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
    )
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_001",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="OHLC inconsistency" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_002_positive_prices(df: pl.DataFrame) -> RuleResult:
    bad = df.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
    )
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_002",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="non-positive price" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_003_nonneg_volume_amount(df: pl.DataFrame) -> RuleResult:
    bad = df.filter((pl.col("volume") < 0) | (pl.col("amount") < 0))
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_003",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="negative volume/amount" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_005_extreme_move(df: pl.DataFrame) -> RuleResult:
    """|close/prev_close - 1| > 50% when prev_close available."""
    if "prev_close" not in df.columns:
        return RuleResult(code="PX_005", level="ERROR", status="pass", detail="skipped")

    with_prev = df.filter(pl.col("prev_close").is_not_null() & (pl.col("prev_close") > 0))
    bad = with_prev.filter(((pl.col("close") / pl.col("prev_close")) - 1.0).abs() > 0.5)
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_005",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="daily move > 50%" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_008_vwap_band(df: pl.DataFrame) -> RuleResult:
    """amount/volume should fall in [low, high] when volume > 0."""
    tradable = df.filter(pl.col("volume") > 0)
    vwap = pl.col("amount") / pl.col("volume")
    bad = tradable.filter((vwap < pl.col("low")) | (vwap > pl.col("high")))
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_008",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="vwap outside [low, high]" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


PRICE_DAILY_RULES: list[RuleFn] = [
    rule_px_001_ohlc,
    rule_px_002_positive_prices,
    rule_px_003_nonneg_volume_amount,
    rule_px_005_extreme_move,
    rule_px_008_vwap_band,
]
