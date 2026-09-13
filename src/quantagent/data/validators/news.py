"""News / announcement validation rules."""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from quantagent.data.validators.report import RuleResult

RuleFn = Callable[[pl.DataFrame], RuleResult]

_REQUIRED = {"source", "source_id", "title", "published_at", "content_hash"}


def rule_news_001_required_columns(df: pl.DataFrame) -> RuleResult:
    missing = sorted(_REQUIRED - set(df.columns))
    return RuleResult(
        code="NEWS_001",
        level="FATAL",
        status="fail" if missing else "pass",
        detail=f"missing columns: {missing}" if missing else "ok",
        affected_count=len(missing),
        affected_keys=missing,
    )


def rule_news_002_nonempty_title(df: pl.DataFrame) -> RuleResult:
    if "title" not in df.columns:
        return RuleResult(code="NEWS_002", level="FATAL", status="pass", detail="skipped")
    empty = pl.col("title").is_null() | (pl.col("title").cast(pl.Utf8).str.len_chars() == 0)
    bad = df.filter(empty)
    return RuleResult(
        code="NEWS_002",
        level="FATAL",
        status="fail" if bad.height else "pass",
        detail="empty title" if bad.height else "ok",
        affected_count=bad.height,
    )


def rule_news_003_published_at_present(df: pl.DataFrame) -> RuleResult:
    if "published_at" not in df.columns:
        return RuleResult(code="NEWS_003", level="FATAL", status="pass", detail="skipped")
    bad = df.filter(pl.col("published_at").is_null())
    return RuleResult(
        code="NEWS_003",
        level="FATAL",
        status="fail" if bad.height else "pass",
        detail="null published_at" if bad.height else "ok",
        affected_count=bad.height,
    )


def rule_news_004_unique_hash(df: pl.DataFrame) -> RuleResult:
    if not {"source", "content_hash"}.issubset(df.columns):
        return RuleResult(code="NEWS_004", level="ERROR", status="pass", detail="skipped")
    dup = df.group_by(["source", "content_hash"]).len().filter(pl.col("len") > 1)
    return RuleResult(
        code="NEWS_004",
        level="ERROR",
        status="fail" if dup.height else "pass",
        detail="duplicate source/content_hash in batch" if dup.height else "ok",
        affected_count=dup.height,
    )


NEWS_RULES: list[RuleFn] = [
    rule_news_001_required_columns,
    rule_news_002_nonempty_title,
    rule_news_003_published_at_present,
    rule_news_004_unique_hash,
]
