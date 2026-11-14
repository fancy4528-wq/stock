"""Unit tests for per-rebalance turnover cap (docs/09 §3.3)."""

from __future__ import annotations

import pytest

from quantagent.decision.portfolio.turnover import limit_turnover, one_way_turnover


def test_one_way_turnover_full_rotation() -> None:
    assert one_way_turnover({"B": 1.0}, {"A": 1.0}) == pytest.approx(1.0)


def test_limit_turnover_passes_when_under_cap() -> None:
    current = {"A": 0.5, "B": 0.5}
    target = {"A": 0.6, "B": 0.4}
    assert one_way_turnover(target, current) == pytest.approx(0.1)
    assert limit_turnover(target, current, max_turnover=0.30) == target


def test_limit_turnover_zero_freezes_book() -> None:
    current = {"A": 0.5, "B": 0.5}
    target = {"C": 1.0}
    assert limit_turnover(target, current, max_turnover=0.0) == current


def test_limit_turnover_prefers_exits_before_entries() -> None:
    current = {"A": 0.5, "B": 0.5}
    target = {"C": 1.0}
    # Budget 0.25 one-way covers one full 0.5 exit (cost 0.25), nothing left for C.
    limited = limit_turnover(target, current, max_turnover=0.25)
    assert "C" not in limited
    assert abs(sum(limited.values()) - 0.5) < 1e-9
    assert one_way_turnover(limited, current) == pytest.approx(0.25)


def test_limit_turnover_rejects_negative_cap() -> None:
    with pytest.raises(ValueError, match="max_turnover"):
        limit_turnover({"A": 1.0}, {}, max_turnover=-0.1)
