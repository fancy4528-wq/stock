"""Unit tests for L2 equal / IC-weighted factor combination."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from quantagent.quant.models.baseline import (
    combine_equal_weight,
    combine_ic_weight,
    ic_weight_dict,
    sign_align_panel,
)


def _dates(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_ic_weight_dict_normalizes_abs() -> None:
    w = ic_weight_dict({"a": 0.04, "b": -0.06})
    assert w["a"] == pytest.approx(0.4)
    assert w["b"] == pytest.approx(-0.6)
    assert abs(w["a"]) + abs(w["b"]) == pytest.approx(1.0)


def test_sign_align_flips_negative_ic_ranks() -> None:
    panel = pl.DataFrame(
        {
            "security_id": [1, 2, 3],
            "trade_date": [date(2024, 1, 2)] * 3,
            "pos": [0.0, 0.5, 1.0],
            "neg": [0.0, 0.5, 1.0],
        }
    )
    out = sign_align_panel(panel, ["pos", "neg"], {"pos": 0.03, "neg": -0.04})
    assert out["pos_aligned"].to_list() == pytest.approx([0.0, 0.5, 1.0])
    assert out["neg_aligned"].to_list() == pytest.approx([1.0, 0.5, 0.0])


def test_equal_weight_cancels_without_sign_align_concept() -> None:
    """Two opposite-signal ranks at extremes: after align, both push same way."""
    panel = pl.DataFrame(
        {
            "security_id": [1, 2],
            "trade_date": [date(2024, 1, 2)] * 2,
            # name1: high pos, high neg-raw → after flip neg becomes low
            "pos": [1.0, 0.0],
            "neg": [1.0, 0.0],
        }
    )
    # Without flip, mean would be 1.0 / 0.0 — mixed signal.
    # With flip on neg: name1 → mean(1.0, 0.0)=0.5; name2 → mean(0.0, 1.0)=0.5
    out = combine_equal_weight(
        panel, ["pos", "neg"], {"pos": 0.05, "neg": -0.05}, out_col="combo"
    )
    assert out["combo"].to_list() == pytest.approx([0.5, 0.5])


def test_equal_weight_same_direction_reinforces() -> None:
    panel = pl.DataFrame(
        {
            "security_id": [1, 2],
            "trade_date": [date(2024, 1, 2)] * 2,
            "a": [1.0, 0.0],
            "b": [0.8, 0.2],
        }
    )
    out = combine_equal_weight(
        panel, ["a", "b"], {"a": 0.03, "b": 0.02}, out_col="combo"
    )
    assert out["combo"][0] > out["combo"][1]


def test_ic_weight_emphasizes_stronger_factor() -> None:
    panel = pl.DataFrame(
        {
            "security_id": [1, 2],
            "trade_date": [date(2024, 1, 2)] * 2,
            "strong": [1.0, 0.0],
            "weak": [0.0, 1.0],
        }
    )
    out = combine_ic_weight(
        panel,
        ["strong", "weak"],
        {"strong": 0.09, "weak": 0.01},
        out_col="combo",
    )
    # Strong dominates → name1 still ranks higher despite weak opposing.
    assert out["combo"][0] > out["combo"][1]


def test_combine_handles_null_component() -> None:
    panel = pl.DataFrame(
        {
            "security_id": [1, 2],
            "trade_date": [date(2024, 1, 2)] * 2,
            "a": [1.0, None],
            "b": [0.5, 0.0],
        }
    )
    out = combine_equal_weight(panel, ["a", "b"], {"a": 0.02, "b": 0.02}, out_col="c")
    assert out["c"][0] == pytest.approx(0.75)
    assert out["c"][1] == pytest.approx(0.0)
