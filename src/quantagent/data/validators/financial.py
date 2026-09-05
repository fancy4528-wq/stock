"""Financial statement validation rules (docs/04-data-sources.md §3.3 subset)."""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from quantagent.data.validators.report import RuleResult

RuleFn = Callable[[pl.DataFrame], RuleResult]


def _row_key(symbol: str, period_end: object, period_type: object) -> str:
    return f"{symbol}|{period_end}|{period_type}"


def rule_fin_001_balance_identity(df: pl.DataFrame) -> RuleResult:
    """total_assets ≈ total_liab + total_equity (1% tolerance)."""
    needed = {"total_assets", "total_liab", "total_equity"}
    if not needed.issubset(df.columns):
        return RuleResult(code="FIN_001", level="ERROR", status="pass", detail="skipped")

    usable = df.filter(
        pl.col("total_assets").is_not_null()
        & pl.col("total_liab").is_not_null()
        & pl.col("total_equity").is_not_null()
        & (pl.col("total_assets").abs() > 0)
    )
    rhs = pl.col("total_liab") + pl.col("total_equity")
    bad = usable.filter(
        ((pl.col("total_assets") - rhs).abs() / pl.col("total_assets").abs()) > 0.01
    )
    keys = [
        _row_key(s, p, t)
        for s, p, t in zip(bad["symbol"], bad["period_end"], bad["period_type"], strict=True)
    ]
    return RuleResult(
        code="FIN_001",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="balance sheet identity break" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_fin_002_announced_after_period(df: pl.DataFrame) -> RuleResult:
    """announced_at.date >= period_end (FATAL)."""
    bad = df.filter(pl.col("announced_at").dt.date() < pl.col("period_end"))
    keys = [
        _row_key(s, p, t)
        for s, p, t in zip(bad["symbol"], bad["period_end"], bad["period_type"], strict=True)
    ]
    return RuleResult(
        code="FIN_002",
        level="FATAL",
        status="fail" if bad.height else "pass",
        detail="announced_at before period_end" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_fin_003_announce_lag(df: pl.DataFrame) -> RuleResult:
    """announced_at within 180 days of period_end (WARN)."""
    lag = (pl.col("announced_at").dt.date() - pl.col("period_end")).dt.total_days()
    bad = df.filter(lag > 180)
    keys = [
        _row_key(s, p, t)
        for s, p, t in zip(bad["symbol"], bad["period_end"], bad["period_type"], strict=True)
    ]
    return RuleResult(
        code="FIN_003",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="announce lag > 180d" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_fin_004_revenue_nonneg(df: pl.DataFrame) -> RuleResult:
    bad = df.filter(pl.col("revenue").is_not_null() & (pl.col("revenue") < 0))
    keys = [
        _row_key(s, p, t)
        for s, p, t in zip(bad["symbol"], bad["period_end"], bad["period_type"], strict=True)
    ]
    return RuleResult(
        code="FIN_004",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="negative revenue" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_fin_006_gross_profit(df: pl.DataFrame) -> RuleResult:
    """gross_profit ≈ revenue - operating_cost (1%)."""
    needed = {"gross_profit", "revenue", "operating_cost"}
    if not needed.issubset(df.columns):
        return RuleResult(code="FIN_006", level="WARN", status="pass", detail="skipped")

    usable = df.filter(
        pl.col("gross_profit").is_not_null()
        & pl.col("revenue").is_not_null()
        & pl.col("operating_cost").is_not_null()
        & (pl.col("revenue").abs() > 0)
    )
    expected = pl.col("revenue") - pl.col("operating_cost")
    bad = usable.filter(
        ((pl.col("gross_profit") - expected).abs() / pl.col("revenue").abs()) > 0.01
    )
    keys = [
        _row_key(s, p, t)
        for s, p, t in zip(bad["symbol"], bad["period_end"], bad["period_type"], strict=True)
    ]
    return RuleResult(
        code="FIN_006",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="gross_profit mismatch" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_fin_009_duplicate_revision_keys(df: pl.DataFrame) -> RuleResult:
    """Duplicate (symbol, period_end, period_type, announced_at) is FATAL."""
    dup = (
        df.group_by(["symbol", "period_end", "period_type", "announced_at"])
        .len()
        .filter(pl.col("len") > 1)
    )
    keys = [
        _row_key(s, p, t)
        for s, p, t in zip(dup["symbol"], dup["period_end"], dup["period_type"], strict=True)
    ]
    return RuleResult(
        code="FIN_009",
        level="FATAL",
        status="fail" if dup.height else "pass",
        detail="duplicate period keys in batch" if dup.height else "ok",
        affected_count=dup.height,
        affected_keys=keys,
    )


FINANCIAL_STATEMENT_RULES: list[RuleFn] = [
    rule_fin_001_balance_identity,
    rule_fin_002_announced_after_period,
    rule_fin_003_announce_lag,
    rule_fin_004_revenue_nonneg,
    rule_fin_006_gross_profit,
    rule_fin_009_duplicate_revision_keys,
]
