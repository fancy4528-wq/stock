"""Unit tests for forward-return labels + tradeability exclusion."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from quantagent.quant.labels import (
    attach_forward_returns,
    entry_untradeable_mask,
    forward_return_col,
    has_tradeability_flags,
    mask_untradeable_labels,
    tradeability_label_stats,
)
from quantagent.quant.labels.targets import LabelError


def _dates(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_forward_return_col() -> None:
    assert forward_return_col(5) == "fwd_ret_5d"
    with pytest.raises(LabelError):
        forward_return_col(0)


def test_attach_without_flags_unchanged() -> None:
    dates = _dates(6)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 6,
            "trade_date": dates,
            "close": [100.0 * (1.01**i) for i in range(6)],
        }
    )
    out = attach_forward_returns(prices, horizons=[1], exclude_untradeable=True)
    assert out["fwd_ret_1d"][0] is not None
    assert abs(float(out["fwd_ret_1d"][0]) - 0.01) < 1e-9


def test_entry_untradeable_mask_uses_t_plus_1() -> None:
    dates = _dates(4)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 4,
            "trade_date": dates,
            "close": [100.0, 101.0, 102.0, 103.0],
            "is_limit_up": [False, True, False, False],
            "is_suspended": [False, False, False, False],
        }
    )
    mask = entry_untradeable_mask(prices, entry_offset=1)
    # Row 0 looks at T+1 (= row 1) limit-up → True
    assert mask.to_list() == [True, False, False, False]


def test_attach_nulls_label_when_t1_limit_up() -> None:
    dates = _dates(5)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 5,
            "trade_date": dates,
            "close": [100.0, 110.0, 111.0, 112.0, 113.0],
            "is_limit_up": [False, True, False, False, False],
            "is_suspended": [False, False, False, False, False],
        }
    )
    out = attach_forward_returns(prices, horizons=[1], exclude_untradeable=True)
    # Signal day 0: entry T+1 is limit-up → label null (even though return exists)
    assert out["fwd_ret_1d"][0] is None
    # Signal day 1: entry T+1 is fine → label kept
    assert out["fwd_ret_1d"][1] is not None


def test_attach_nulls_label_when_t1_suspended() -> None:
    dates = _dates(4)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 4,
            "trade_date": dates,
            "close": [100.0, 100.0, 101.0, 102.0],
            "is_limit_up": [False, False, False, False],
            "is_suspended": [False, True, False, False],
        }
    )
    out = attach_forward_returns(prices, horizons=[1])
    assert out["fwd_ret_1d"][0] is None
    assert out["fwd_ret_1d"][1] is not None


def test_exclude_untradeable_false_keeps_label() -> None:
    dates = _dates(4)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 4,
            "trade_date": dates,
            "close": [100.0, 110.0, 111.0, 112.0],
            "is_limit_up": [False, True, False, False],
            "is_suspended": [False, False, False, False],
        }
    )
    out = attach_forward_returns(prices, horizons=[1], exclude_untradeable=False)
    assert out["fwd_ret_1d"][0] is not None
    assert abs(float(out["fwd_ret_1d"][0]) - 0.10) < 1e-9


def test_mask_untradeable_labels_helper() -> None:
    dates = _dates(3)
    panel = pl.DataFrame(
        {
            "security_id": [1] * 3,
            "trade_date": dates,
            "close": [1.0, 2.0, 3.0],
            "is_limit_up": [False, True, False],
            "is_suspended": [False, False, False],
            "fwd_ret_5d": [0.1, 0.2, 0.3],
        }
    )
    out = mask_untradeable_labels(panel, ["fwd_ret_5d"], entry_offset=1)
    assert out["fwd_ret_5d"][0] is None
    assert out["fwd_ret_5d"][1] == pytest.approx(0.2)


def test_tradeability_stats() -> None:
    dates = _dates(3)
    panel = pl.DataFrame(
        {
            "security_id": [1] * 3,
            "trade_date": dates,
            "close": [1.0, 2.0, 3.0],
            "is_limit_up": [False, True, False],
            "is_suspended": [False, False, True],
        }
    )
    assert has_tradeability_flags(panel)
    stats = tradeability_label_stats(panel)
    # entry at T+1: row0→limit_up, row1→suspended, row2→False
    assert stats["n_untradeable_entry"] == 2
    assert stats["flags_present"] == 1
