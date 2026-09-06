"""Industry membership validation rules."""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from quantagent.data.validators.report import RuleResult

RuleFn = Callable[[pl.DataFrame], RuleResult]


def rule_ind_001_required_columns(df: pl.DataFrame) -> RuleResult:
    required = {"record_type", "taxonomy_code", "industry_code", "source"}
    missing = sorted(required - set(df.columns))
    return RuleResult(
        code="IND_001",
        level="FATAL",
        status="fail" if missing else "pass",
        detail=f"missing columns: {missing}" if missing else "ok",
        affected_count=len(missing),
        affected_keys=missing,
    )


def rule_ind_002_membership_symbol(df: pl.DataFrame) -> RuleResult:
    if "record_type" in df.columns:
        members = df.filter(pl.col("record_type") == "membership")
    else:
        members = df
    if members.is_empty():
        return RuleResult(code="IND_002", level="ERROR", status="pass", detail="no memberships")
    bad = members.filter(pl.col("symbol").is_null() | (pl.col("symbol").cast(pl.Utf8) == ""))
    if "industry_code" in bad.columns:
        keys = [str(s) for s in bad["industry_code"].to_list()]
    else:
        keys = []
    return RuleResult(
        code="IND_002",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="membership missing symbol" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


def rule_ind_003_unique_l1_symbol(df: pl.DataFrame) -> RuleResult:
    """Each symbol has at most one open L1 membership in the batch."""
    if "record_type" not in df.columns:
        return RuleResult(code="IND_003", level="FATAL", status="pass", detail="skipped")
    members = df.filter(
        (pl.col("record_type") == "membership")
        & (pl.col("level") == 1)
        & (pl.col("valid_to").is_null())
    )
    if members.is_empty():
        return RuleResult(code="IND_003", level="FATAL", status="pass", detail="ok")
    dup = (
        members.group_by("symbol")
        .len()
        .filter(pl.col("len") > 1)
    )
    keys = [str(s) for s in dup["symbol"].to_list()]
    return RuleResult(
        code="IND_003",
        level="FATAL",
        status="fail" if dup.height else "pass",
        detail="duplicate open L1 membership" if dup.height else "ok",
        affected_count=dup.height,
        affected_keys=keys,
    )


def rule_ind_004_valid_from(df: pl.DataFrame) -> RuleResult:
    if "record_type" in df.columns:
        members = df.filter(pl.col("record_type") == "membership")
    else:
        members = df
    if members.is_empty():
        return RuleResult(code="IND_004", level="ERROR", status="pass", detail="ok")
    bad = members.filter(pl.col("valid_from").is_null())
    keys = [str(s) for s in bad["symbol"].to_list()] if "symbol" in bad.columns else []
    return RuleResult(
        code="IND_004",
        level="ERROR",
        status="fail" if bad.height else "pass",
        detail="membership missing valid_from" if bad.height else "ok",
        affected_count=bad.height,
        affected_keys=keys,
    )


INDUSTRY_RULES: list[RuleFn] = [
    rule_ind_001_required_columns,
    rule_ind_002_membership_symbol,
    rule_ind_003_unique_l1_symbol,
    rule_ind_004_valid_from,
]
