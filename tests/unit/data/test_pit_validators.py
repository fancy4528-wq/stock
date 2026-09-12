"""Unit tests for PIT integrity validators (mocked Connection)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from quantagent.data.validators.pit import (
    compare_adjust_factors,
    rule_pit_001_announced_before_ingested,
    rule_pit_003_no_interval_overlap,
    rule_pit_005_snapshot_on_rebalance,
    rule_pit_006_no_price_after_delist,
    rule_pit_007_delisted_security_retained,
    run_pit_checks,
)


def test_rule_pit_001_pass_and_fail() -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.side_effect = [0, 0]
    ok = rule_pit_001_announced_before_ingested(conn)
    assert ok.status == "pass"

    conn.execute.return_value.scalar_one.side_effect = [2, 0]
    bad = rule_pit_001_announced_before_ingested(conn)
    assert bad.status == "fail"
    assert bad.affected_count == 1
    assert "financial_statement" in bad.affected_keys[0]


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


def test_run_pit_checks_aggregates() -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 0
    conn.execute.return_value.mappings.return_value.all.return_value = []
    report = run_pit_checks(conn, check_date=date(2020, 1, 1), rebalance_dates=[])
    assert report.dataset == "pit_integrity"
    assert report.check_date == date(2020, 1, 1)
    assert len(report.results) == 5


def test_compare_adjust_factors() -> None:
    ok = compare_adjust_factors(factor_a=1.0, factor_b=1.0001, threshold=0.001)
    assert ok.status == "pass"

    bad = compare_adjust_factors(factor_a=1.0, factor_b=1.01, threshold=0.001)
    assert bad.status == "warn"

    zero = compare_adjust_factors(factor_a=0.0, factor_b=0.01, threshold=0.001)
    assert zero.status == "warn"
