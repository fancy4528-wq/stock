"""HoldoutGuard: one use, walk-forward stays outside the seal."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.quant.training.holdout_guard import (
    HoldoutGuard,
    HoldoutViolation,
    load_holdout_guard,
)
from quantagent.quant.training.walk_forward import WalkForwardConfig, generate_folds


def test_check_access_allows_first_use_and_blocks_second(tmp_path) -> None:
    guard = HoldoutGuard(date(2026, 10, 14), tmp_path / "uses.jsonl")
    guard.check_access(date(2026, 10, 13), "before seal")
    assert guard.uses() == []

    guard.check_access(date(2026, 10, 14), "final validation")
    uses = guard.uses()
    assert len(uses) == 1
    assert uses[0].purpose == "final validation"
    assert uses[0].end_date == date(2026, 10, 14)

    with pytest.raises(HoldoutViolation, match="封存期已使用过 1 次"):
        guard.check_access(date(2026, 12, 31), "second look")
    assert len(guard.uses()) == 1


def test_assert_excluded_does_not_consume_the_use(tmp_path) -> None:
    guard = HoldoutGuard(date(2026, 10, 14), tmp_path / "uses.jsonl")
    guard.assert_excluded(date(2026, 10, 13))
    with pytest.raises(HoldoutViolation, match="check_access"):
        guard.assert_excluded(date(2026, 10, 14))
    assert guard.uses() == []
    guard.check_access(date(2026, 10, 16), "still available")
    assert len(guard.uses()) == 1


def test_corrupt_log_fails_closed(tmp_path) -> None:
    path = tmp_path / "uses.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    guard = HoldoutGuard(date(2026, 10, 14), path)
    with pytest.raises(HoldoutViolation, match="unreadable"):
        guard.check_access(date(2026, 10, 14), "retry")


def test_generate_folds_stop_before_holdout(tmp_path) -> None:
    seal = date(2022, 1, 1)
    guard = HoldoutGuard(seal, tmp_path / "uses.jsonl")
    cfg = WalkForwardConfig(
        train_months=6,
        val_months=2,
        test_months=2,
        step_months=2,
        embargo_days=5,
        holdout_start=seal,
    )
    folds = generate_folds(date(2020, 1, 1), date(2022, 6, 30), cfg, guard=guard)
    assert folds
    assert all(f.test_end < seal for f in folds)
    assert guard.uses() == []

    bare = generate_folds(
        date(2020, 1, 1),
        date(2022, 6, 30),
        WalkForwardConfig(
            train_months=6,
            val_months=2,
            test_months=2,
            step_months=2,
            embargo_days=5,
            holdout_start=seal,
        ),
    )
    assert bare[-1].test_end <= seal - timedelta(days=1)


def test_generate_folds_rejects_mismatched_seal(tmp_path) -> None:
    guard = HoldoutGuard(date(2022, 1, 1), tmp_path / "uses.jsonl")
    cfg = WalkForwardConfig(
        train_months=6,
        val_months=2,
        test_months=2,
        step_months=2,
        embargo_days=5,
        holdout_start=date(2022, 6, 1),
    )
    with pytest.raises(ValueError, match="holdout_start mismatch"):
        generate_folds(date(2020, 1, 1), date(2022, 12, 31), cfg, guard=guard)


def test_load_cn_holdout_is_frozen_after_l4_panel() -> None:
    guard = load_holdout_guard("CN")
    assert guard.holdout_start == date(2026, 10, 14)
    assert guard.log_path.name == "cn_uses.jsonl"
    assert guard.uses() == []
