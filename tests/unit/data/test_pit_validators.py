"""Unit tests for PIT integrity validators (mocked Connection)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from quantagent.data.validators.pit import (
    compare_adjust_factors,
    rule_pit_001_announced_before_ingested,
    rule_pit_002_announced_at_required,
    rule_pit_003_no_interval_overlap,
    rule_pit_005_snapshot_on_rebalance,
    rule_pit_006_no_price_after_delist,
    rule_pit_007_delisted_security_retained,
    rule_pit_008_document_chunk_visible_at,
    run_pit_checks,
)


def test_rule_pit_001_pass_and_fail() -> None:
    conn = MagicMock()
    # exists, count, exists, count
    conn.execute.return_value.scalar_one.side_effect = [True, 0, True, 0]
    ok = rule_pit_001_announced_before_ingested(conn)
    assert ok.status == "pass"

    conn.execute.return_value.scalar_one.side_effect = [True, 2, True, 0]
    bad = rule_pit_001_announced_before_ingested(conn)
    assert bad.status == "fail"
    assert bad.affected_count == 1
    assert "financial_statement" in bad.affected_keys[0]


def test_rule_pit_002_null_announced() -> None:
    conn = MagicMock()
    # 4 tables × (exists + has_column + count) — only first table present
    # financial_statement: exists True, col True, count 0
    # others: exists False
    conn.execute.return_value.scalar_one.side_effect = [
        True,
        1,  # column exists
        0,  # null count
        False,
        False,
        False,
    ]
    ok = rule_pit_002_announced_at_required(conn)
    assert ok.status == "pass"

    conn.execute.return_value.scalar_one.side_effect = [
        True,
        1,
        3,  # nulls
        False,
        False,
        False,
    ]
    bad = rule_pit_002_announced_at_required(conn)
    assert bad.status == "fail"
    assert bad.code == "PIT_002"
    assert "financial_statement:3" in bad.affected_keys


def test_rule_pit_002_skipped_when_absent() -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = False
    skipped = rule_pit_002_announced_at_required(conn)
    assert skipped.status == "pass"
    assert "skipped" in skipped.detail


def test_rule_pit_003_overlap() -> None:
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = []
    assert rule_pit_003_no_interval_overlap(conn).status == "pass"

    conn.execute.return_value.mappings.return_value.all.return_value = [
        {"security_id": 1, "industry_id": 2, "valid_from": date(2020, 1, 1)}
    ]
    bad = rule_pit_003_no_interval_overlap(conn)
    assert bad.status == "fail"
    assert bad.affected_keys == ["1|2|2020-01-01"]


def test_rule_pit_005_skipped_and_missing() -> None:
    conn = MagicMock()
    skipped = rule_pit_005_snapshot_on_rebalance(conn, rebalance_dates=None)
    assert skipped.status == "pass"
    assert skipped.detail == "skipped"

    conn.execute.return_value.scalar_one.side_effect = [0, 3]
    missing = rule_pit_005_snapshot_on_rebalance(
        conn,
        rebalance_dates=[date(2020, 1, 1), date(2020, 2, 1)],
    )
    assert missing.status == "fail"
    assert missing.affected_keys == ["2020-01-01"]


def test_rule_pit_006_and_007() -> None:
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = []
    assert rule_pit_006_no_price_after_delist(conn).status == "pass"
    assert rule_pit_007_delisted_security_retained(conn).status == "pass"

    conn.execute.return_value.mappings.return_value.all.return_value = [
        {"symbol": "600001.SH", "trade_date": date(2021, 1, 1)}
    ]
    warn = rule_pit_006_no_price_after_delist(conn)
    assert warn.status == "warn"

    conn.execute.return_value.mappings.return_value.all.return_value = [{"security_id": 99}]
    fatal = rule_pit_007_delisted_security_retained(conn)
    assert fatal.status == "fail"
    assert fatal.affected_keys == ["99"]


def test_rule_pit_008_absent_and_fail() -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = False
    skipped = rule_pit_008_document_chunk_visible_at(conn)
    assert skipped.status == "pass"
    assert "skipped" in skipped.detail

    # table exists, visible_at col exists, nulls=2, ingested_at col exists, late=1
    conn.execute.return_value.scalar_one.side_effect = [
        True,  # relation
        1,  # visible_at col
        2,  # null count
        1,  # ingested_at col
        1,  # late count
    ]
    bad = rule_pit_008_document_chunk_visible_at(conn)
    assert bad.status == "fail"
    assert bad.code == "PIT_008"
    assert any("visible_at_null" in k for k in bad.affected_keys)
    assert any("ingested_at" in k for k in bad.affected_keys)


def test_run_pit_checks_aggregates() -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 0
    conn.execute.return_value.mappings.return_value.all.return_value = []
    report = run_pit_checks(conn, check_date=date(2020, 1, 1), rebalance_dates=[])
    assert report.dataset == "pit_integrity"
    assert report.check_date == date(2020, 1, 1)
    codes = [r.code for r in report.results]
    assert codes == [
        "PIT_001",
        "PIT_002",
        "PIT_003",
        "PIT_005",
        "PIT_006",
        "PIT_007",
        "PIT_008",
    ]


def test_compare_adjust_factors() -> None:
    ok = compare_adjust_factors(factor_a=1.0, factor_b=1.0001, threshold=0.001)
    assert ok.status == "pass"

    bad = compare_adjust_factors(factor_a=1.0, factor_b=1.01, threshold=0.001)
    assert bad.status == "warn"

    zero = compare_adjust_factors(factor_a=0.0, factor_b=0.01, threshold=0.001)
    assert zero.status == "warn"
