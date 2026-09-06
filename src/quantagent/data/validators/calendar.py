"""Trading calendar validation rules."""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from quantagent.data.validators.report import RuleResult

RuleFn = Callable[[pl.DataFrame], RuleResult]


def rule_cal_001_required_columns(df: pl.DataFrame) -> RuleResult:
    required = {"market", "trade_date", "is_open"}
    missing = sorted(required - set(df.columns))
    return RuleResult(
        code="CAL_001",
        level="FATAL",
        status="fail" if missing else "pass",
        detail=f"missing columns: {missing}" if missing else "ok",
        affected_count=len(missing),
        affected_keys=missing,
    )


def rule_cal_002_has_open_days(df: pl.DataFrame) -> RuleResult:
    if "is_open" not in df.columns:
        return RuleResult(code="CAL_002", level="ERROR", status="pass", detail="skipped")
    n_open = int(df.filter(pl.col("is_open")).height)
    return RuleResult(
        code="CAL_002",
        level="ERROR",
        status="fail" if n_open == 0 else "pass",
        detail="no open trading days" if n_open == 0 else f"open_days={n_open}",
        affected_count=0 if n_open else df.height,
    )


def rule_cal_003_unique_dates(df: pl.DataFrame) -> RuleResult:
    if "trade_date" not in df.columns or "market" not in df.columns:
        return RuleResult(code="CAL_003", level="ERROR", status="pass", detail="skipped")
    dup = (
        df.group_by(["market", "trade_date"])
        .len()
        .filter(pl.col("len") > 1)
    )
    keys = [
        f"{m}|{d}"
        for m, d in zip(dup["market"], dup["trade_date"], strict=True)
    ]
    return RuleResult(
        code="CAL_003",
        level="FATAL",
        status="fail" if dup.height else "pass",
        detail="duplicate market/trade_date" if dup.height else "ok",
        affected_count=dup.height,
        affected_keys=keys,
    )


def rule_cal_004_open_neighbors(df: pl.DataFrame) -> RuleResult:
    """Open days (except ends) should have prev/next trade dates."""
    if not {"is_open", "prev_trade_date", "next_trade_date", "trade_date"}.issubset(
        df.columns
    ):
        return RuleResult(code="CAL_004", level="WARN", status="pass", detail="skipped")
    opens = df.filter(pl.col("is_open")).sort("trade_date")
    if opens.height < 3:
        return RuleResult(code="CAL_004", level="WARN", status="pass", detail="too few")
    mid = opens.slice(1, opens.height - 2)
    bad = mid.filter(
        pl.col("prev_trade_date").is_null() | pl.col("next_trade_date").is_null()
    )
    keys = [str(d) for d in bad["trade_date"].to_list()]
    return RuleResult(
        code="CAL_004",
        level="WARN",
        status="warn" if bad.height else "pass",
        detail="open day missing prev/next" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


CALENDAR_RULES: list[RuleFn] = [
    rule_cal_001_required_columns,
    rule_cal_002_has_open_days,
    rule_cal_003_unique_dates,
    rule_cal_004_open_neighbors,
]
