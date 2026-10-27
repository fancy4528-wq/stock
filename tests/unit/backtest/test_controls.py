"""Unit tests for Gate 4 control helpers (no DB)."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.backtest.controls import (
    ControlSuiteResult,
    equal_pool_scores,
    pick_best_single_factor,
    random_topn_scores,
    scores_from_single_factor,
)


def test_pick_best_prefers_documented_leader() -> None:
    means = {"max_ret_20d": -0.04, "vol_60d": -0.05, "bp": 0.03}
    assert pick_best_single_factor(means, list(means)) == "max_ret_20d"
    assert pick_best_single_factor(means, list(means), preferred=None) == "vol_60d"


def test_equal_pool_scores_deterministic_prefix() -> None:
    d0 = date(2024, 1, 2)
    membership = {d0: frozenset({"CCC", "AAA", "BBB", "DDD"})}
    scores = equal_pool_scores(membership, pool_n=2)
    assert scores[d0] == {"AAA": 1.0, "BBB": 1.0}


def test_random_topn_scores_reproducible() -> None:
    d0 = date(2024, 1, 2)
    membership = {d0: frozenset({f"S{i:02d}" for i in range(20)})}
    a = random_topn_scores(membership, top_n=5, seed=7)
    b = random_topn_scores(membership, top_n=5, seed=7)
    c = random_topn_scores(membership, top_n=5, seed=8)
    assert a == b
    assert set(a[d0]) != set(c[d0]) or a[d0] != c[d0]
    assert len(a[d0]) == 5


def test_scores_from_single_factor_sign_align_and_membership() -> None:
    d0, d1 = date(2024, 1, 2), date(2024, 1, 3)
    panel = pl.DataFrame(
        {
            "trade_date": [d0, d0, d1],
            "symbol": ["AAA", "BBB", "AAA"],
            "max_ret_20d": [0.2, 0.8, 0.5],
        }
    )
    membership = {d0: frozenset({"AAA"}), d1: frozenset({"AAA"})}
    # Negative IC → flip so lower raw rank becomes higher score.
    scores = scores_from_single_factor(
        panel, "max_ret_20d", -0.05, start=d0, end=d1, membership=membership
    )
    assert scores[d0] == {"AAA": 0.8}  # 1 - 0.2; BBB filtered out
    assert scores[d1] == {"AAA": 0.5}


def test_control_suite_report_strings() -> None:
    suite = ControlSuiteResult(
        buy_and_hold=-0.13,
        equal_weight_pool=-0.10,
        best_single_factor=-0.08,
        best_single_factor_code="max_ret_20d",
        l2_equal=-0.05,
        strategy=-0.05,
        random_p95=-0.06,
        random_p50=-0.12,
        random_p80=-0.09,
        n_trials=100,
        pool_n=50,
        beats_random_p95=True,
    )
    ctrl = suite.as_report_controls()
    assert "+✅" in ctrl["random_p95"] or "超出随机" in ctrl["random_p95"]
    assert "`max_ret_20d`" in ctrl["best_single_factor"]
    assert "n=50" in ctrl["equal_weight_pool"]
