"""Signal journal and independence check."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import polars as pl
import pytest

from quantagent.evaluation.signals import (
    SignalScoreDay,
    append_signal_score_day,
    check_signal_independence,
    load_signal_score_days,
    write_signal_corr_report,
)
from quantagent.evaluation.signals.correlation import SignalCorrError


def _day(
    as_of: date,
    *,
    factor: dict[str, float],
    quant: dict[str, float],
    stock: dict[str, float] | None = None,
    origin: Literal["live", "synthetic"] = "live",
) -> SignalScoreDay:
    signals: dict[str, dict[str, float]] = {"factor": factor, "quant": quant}
    if stock is not None:
        signals["stock"] = stock
    return SignalScoreDay(
        as_of=as_of,
        run_id=as_of.isoformat(),
        origin=origin,
        signals=signals,
    )


def test_journal_skips_empty_and_duplicate_day(tmp_path: Path) -> None:
    empty = SignalScoreDay(as_of=date(2026, 10, 30), run_id="r", signals={})
    assert append_signal_score_day(tmp_path, empty) is False
    day = _day(
        date(2026, 10, 30),
        factor={"A": 1.0},
        quant={"A": 2.0},
    )
    assert append_signal_score_day(tmp_path, day) is True
    assert append_signal_score_day(tmp_path, day) is False
    loaded = load_signal_score_days(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].signals["quant"]["A"] == pytest.approx(2.0)
    assert load_signal_score_days(tmp_path / "missing") == []


def test_short_window_is_tracking_and_does_not_change_weights() -> None:
    symbols = [f"S{i}" for i in range(6)]
    factor = {sym: float(i) for i, sym in enumerate(symbols)}
    quant = dict(factor)
    stock = {sym: float(5 - i) for i, sym in enumerate(symbols)}
    result = check_signal_independence(
        [_day(date(2026, 10, 30), factor=factor, quant=quant, stock=stock)]
    )
    by_pair = {(pair.left, pair.right): pair for pair in result.pairs}
    assert by_pair[("factor", "quant")].corr == pytest.approx(1.0)
    assert by_pair[("factor", "quant")].flag == "tracking"
    assert by_pair[("factor", "stock")].corr == pytest.approx(-1.0)
    assert result.weights_changed is False
    assert "sector" in result.missing_fusion_slots
    assert "不改" in result.interpretation


def test_twenty_days_flags_merge_and_ok() -> None:
    symbols = [f"S{i}" for i in range(6)]
    factor = {sym: float(i + 1) for i, sym in enumerate(symbols)}
    quant = dict(factor)
    stock = {"S0": 6.0, "S1": 1.0, "S2": 3.0, "S3": 4.0, "S4": 5.0, "S5": 2.0}
    start = date(2026, 9, 1)
    days = [
        _day(start + timedelta(days=i), factor=factor, quant=quant, stock=stock)
        for i in range(20)
    ]
    result = check_signal_independence(days)
    by_pair = {(pair.left, pair.right): pair for pair in result.pairs}
    assert by_pair[("factor", "quant")].flag == "merge"
    assert by_pair[("factor", "quant")].n_days == 20
    assert by_pair[("quant", "stock")].flag == "ok"
    assert abs(by_pair[("quant", "stock")].corr) < 0.7
    assert result.weights_changed is False
    assert "应合并" in result.interpretation
    assert "不修改 FusionConfig" in result.interpretation


def test_synthetic_rows_are_ignored() -> None:
    symbols = [f"S{i}" for i in range(6)]
    scores = {sym: float(i) for i, sym in enumerate(symbols)}
    day = _day(
        date(2026, 10, 30),
        factor=scores,
        quant=scores,
        origin="synthetic",
    )
    result = check_signal_independence([day])
    assert result.n_days == 0
    assert result.pairs == []
    assert "未算出" in result.interpretation
    included = check_signal_independence([day], include_synthetic=True)
    assert included.n_days == 1


def test_standalone_ic_uses_forward_returns() -> None:
    symbols = [f"S{i}" for i in range(6)]
    score = {sym: float(i) for i, sym in enumerate(symbols)}
    as_of = date(2026, 10, 1)
    days = [_day(as_of, factor=score, quant=score)]
    rows: list[dict[str, object]] = []
    for offset in range(8):
        trade_date = as_of + timedelta(days=offset)
        for i, sym in enumerate(symbols):
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": trade_date,
                    "close": 100.0 + i * offset,
                }
            )
    result = check_signal_independence(days, prices=pl.DataFrame(rows))
    factor_5d = next(
        stat for stat in result.ics if stat.signal == "factor" and stat.horizon == "5d"
    )
    assert factor_5d.n_days == 1
    assert factor_5d.ic_mean == pytest.approx(1.0)


def test_prices_missing_columns_raise() -> None:
    symbols = [f"S{i}" for i in range(6)]
    scores = {sym: float(i) for i, sym in enumerate(symbols)}
    with pytest.raises(SignalCorrError):
        check_signal_independence(
            [_day(date(2026, 10, 1), factor=scores, quant=scores)],
            prices=pl.DataFrame({"symbol": ["A"]}),
        )


def test_report_lists_pairs(tmp_path: Path) -> None:
    symbols = [f"S{i}" for i in range(6)]
    scores = {sym: float(i) for i, sym in enumerate(symbols)}
    result = check_signal_independence(
        [_day(date(2026, 10, 30), factor=scores, quant=scores)]
    )
    path = write_signal_corr_report(result, tmp_path / "signal-corr.md")
    text = path.read_text(encoding="utf-8")
    assert "信号相关矩阵" in text
    assert "factor" in text
    assert "本次是否修改权重 | 否" in text
