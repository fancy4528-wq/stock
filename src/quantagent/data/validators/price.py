"""Price daily validation rules (docs/04-data-sources.md §3.2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import polars as pl

from quantagent.data.validators.report import RuleResult

if TYPE_CHECKING:
    from quantagent.data.validators import ValidationContext

RuleFn = Callable[..., RuleResult]


def _row_key(symbol: str, trade_date: object) -> str:
    return f"{symbol}|{trade_date}"


def _extra(ctx: ValidationContext | None) -> dict[str, Any]:
    if ctx is None:
        return {}
    return dict(ctx.extra or {})


def rule_px_001_ohlc(df: pl.DataFrame, ctx: ValidationContext | None = None) -> RuleResult:
    """high >= low; high >= open/close; low <= open/close."""
    del ctx
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


def rule_px_002_positive_prices(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    del ctx
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


def rule_px_003_nonneg_volume_amount(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    del ctx
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


def rule_px_004_within_limits(df: pl.DataFrame, ctx: ValidationContext | None = None) -> RuleResult:
    """Close should stay within enriched limit_up_px / limit_down_px (ST/board-aware)."""
    del ctx
    needed = {"limit_up_px", "limit_down_px", "close"}
    if not needed.issubset(df.columns):
        return RuleResult(code="PX_004", level="WARN", status="pass", detail="skipped")

    usable = df.filter(
        pl.col("limit_up_px").is_not_null()
        & pl.col("limit_down_px").is_not_null()
        & pl.col("close").is_not_null()
    )
    # Small float tolerance for tick rounding after limit enrichment.
    eps = 1e-4
    bad = usable.filter(
        (pl.col("close") > pl.col("limit_up_px") * (1.0 + eps))
        | (pl.col("close") < pl.col("limit_down_px") * (1.0 - eps))
    )
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_004",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="close outside limit band" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_005_extreme_move(df: pl.DataFrame, ctx: ValidationContext | None = None) -> RuleResult:
    """|close/prev_close - 1| > 50% when prev_close available."""
    del ctx
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


def rule_px_006_trading_day_coverage(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    """Open trading days must have a bar per universe symbol (suspended exempt)."""
    extra = _extra(ctx)
    if not extra.get("is_trading_day", True):
        return RuleResult(
            code="PX_006",
            level="ERROR",
            status="pass",
            detail="non-trading day skipped",
        )
    expected = {str(s) for s in (extra.get("universe_symbols") or [])}
    if not expected:
        return RuleResult(code="PX_006", level="ERROR", status="pass", detail="skipped")

    present = set(df["symbol"].cast(pl.Utf8).to_list()) if "symbol" in df.columns else set()
    suspended = {str(s) for s in (extra.get("suspended_symbols") or [])}
    if "is_suspended" in df.columns:
        suspended |= {
            str(s) for s in df.filter(pl.col("is_suspended"))["symbol"].cast(pl.Utf8).to_list()
        }
    missing = sorted(expected - present - suspended)
    return RuleResult(
        code="PX_006",
        level="ERROR",
        status="fail" if missing else "pass",
        detail=f"missing bars on open day: {missing[:5]}" if missing else "ok",
        affected_count=len(missing),
        affected_keys=missing,
    )


def rule_px_007_suspended_zero_volume(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    """Suspended days should not have positive volume."""
    del ctx
    if "is_suspended" not in df.columns:
        return RuleResult(code="PX_007", level="WARN", status="pass", detail="skipped")
    bad = df.filter(pl.col("is_suspended") & (pl.col("volume") > 0))
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_007",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="suspended with volume>0" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_008_vwap_band(df: pl.DataFrame, ctx: ValidationContext | None = None) -> RuleResult:
    """amount/volume should fall in [low, high] when volume > 0."""
    del ctx
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


def rule_px_009_dual_source_price(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    """Dual-source close difference > 0.5% → ERROR.

    Expects columns ``close_a`` / ``close_b`` (or ``close`` + ``close_peer``).
    """
    del ctx
    if "close_a" in df.columns and "close_b" in df.columns:
        a_col, b_col = "close_a", "close_b"
    elif "close" in df.columns and "close_peer" in df.columns:
        a_col, b_col = "close", "close_peer"
    else:
        return RuleResult(code="PX_009", level="ERROR", status="pass", detail="skipped")

    usable = df.filter(
        pl.col(a_col).is_not_null() & pl.col(b_col).is_not_null() & (pl.col(a_col) > 0)
    )
    bad = usable.filter(((pl.col(a_col) - pl.col(b_col)).abs() / pl.col(a_col)) > 0.005)
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_009",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="dual-source close diff > 0.5%" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_px_010_stuck_price(df: pl.DataFrame, ctx: ValidationContext | None = None) -> RuleResult:
    """Warn when a symbol has ≥5 consecutive identical closes in the batch."""
    del ctx
    if not {"symbol", "trade_date", "close"}.issubset(df.columns):
        return RuleResult(code="PX_010", level="WARN", status="pass", detail="skipped")

    ordered = df.sort(["symbol", "trade_date"])
    stuck_keys: list[str] = []
    for key, group in ordered.group_by("symbol", maintain_order=True):
        sym = key[0] if isinstance(key, tuple) else key
        closes = group["close"].to_list()
        dates = group["trade_date"].to_list()
        run = 1
        for i in range(1, len(closes)):
            if closes[i] == closes[i - 1]:
                run += 1
                if run >= 5:
                    stuck_keys.append(_row_key(str(sym), dates[i]))
            else:
                run = 1
    seen: set[str] = set()
    keys: list[str] = []
    for k in stuck_keys:
        if k not in seen:
            seen.add(k)
            keys.append(k)
    return RuleResult(
        code="PX_010",
        level="WARN",
        status="warn" if keys else "pass",
        detail="≥5 identical closes" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def rule_px_011_universe_coverage(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    """Universe coverage must be ≥ 99%."""
    extra = _extra(ctx)
    expected = extra.get("expected_count")
    if expected is None:
        symbols = extra.get("universe_symbols") or []
        expected = len(symbols) if symbols else None
    if not expected:
        return RuleResult(code="PX_011", level="ERROR", status="pass", detail="skipped")
    n = int(df["symbol"].n_unique()) if "symbol" in df.columns and df.height else 0
    coverage = n / float(expected)
    failed = coverage < 0.99
    return RuleResult(
        code="PX_011",
        level="ERROR",
        status="fail" if failed else "pass",
        detail=f"coverage {n}/{expected}={coverage:.2%}" if failed else "ok",
        affected_count=max(0, int(expected) - n),
        affected_keys=[],
        expected={"min_coverage": 0.99, "expected_count": int(expected)},
        actual={"n": n, "coverage": coverage},
    )


def rule_px_012_prev_close_ex_div(
    df: pl.DataFrame, ctx: ValidationContext | None = None
) -> RuleResult:
    """prev_close ≠ prior session close without an ex-div / adjust record → ERROR.

    Requires ``prior_close`` (previous trading day's close) and optional
    ``has_adjust_factor`` (bool). Rows without ``prior_close`` are skipped.
    """
    del ctx
    if "prev_close" not in df.columns or "prior_close" not in df.columns:
        return RuleResult(code="PX_012", level="ERROR", status="pass", detail="skipped")

    usable = df.filter(
        pl.col("prev_close").is_not_null()
        & pl.col("prior_close").is_not_null()
        & (pl.col("prior_close") > 0)
    )
    mismatch = usable.filter((pl.col("prev_close") - pl.col("prior_close")).abs() > 1e-4)
    if "has_adjust_factor" in mismatch.columns:
        bad = mismatch.filter(~pl.col("has_adjust_factor").fill_null(False))
    else:
        bad = mismatch
    keys = [_row_key(s, d) for s, d in zip(bad["symbol"], bad["trade_date"], strict=True)]
    return RuleResult(
        code="PX_012",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="prev_close≠prior_close without adjust record" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


PRICE_DAILY_RULES: list[RuleFn] = [
    rule_px_001_ohlc,
    rule_px_002_positive_prices,
    rule_px_003_nonneg_volume_amount,
    rule_px_004_within_limits,
    rule_px_005_extreme_move,
    rule_px_006_trading_day_coverage,
    rule_px_007_suspended_zero_volume,
    rule_px_008_vwap_band,
    rule_px_009_dual_source_price,
    rule_px_010_stuck_price,
    rule_px_011_universe_coverage,
    rule_px_012_prev_close_ex_div,
]
