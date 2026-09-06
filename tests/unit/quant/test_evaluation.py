"""Unit tests for forward-return labels and factor evaluation (W6)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from quantagent.quant.evaluation import (
    cross_sectional_spearman,
    daily_ic_series,
    evaluate_factor,
    evaluate_factors,
    ic_decay,
    passes_admission,
    quantile_analysis,
    render_factor_report,
    summarize_ic,
    synthetic_eval_panel,
    write_factor_report,
)
from quantagent.quant.evaluation.types import FactorTestResult
from quantagent.quant.labels import attach_forward_returns, forward_return_col
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


def test_attach_forward_returns_exact() -> None:
    dates = _dates(10)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 10,
            "trade_date": dates,
            "close": [100.0 * (1.01**i) for i in range(10)],
        }
    )
    out = attach_forward_returns(prices, horizons=[5])
    # close_{t+5}/close_t - 1 = 1.01**5 - 1
    expected = 1.01**5 - 1.0
    val = out["fwd_ret_5d"][0]
    assert val is not None
    assert abs(float(val) - expected) < 1e-9
    assert out["fwd_ret_5d"][-1] is None


def test_cross_sectional_spearman_perfect() -> None:
    x = pl.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    y = pl.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    assert cross_sectional_spearman(x, y) == pytest.approx(1.0)


def test_cross_sectional_spearman_inverse() -> None:
    x = pl.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    y = pl.Series([50.0, 40.0, 30.0, 20.0, 10.0])
    assert cross_sectional_spearman(x, y) == pytest.approx(-1.0)


def test_summarize_ic_constant() -> None:
    s = summarize_ic([0.05] * 20)
    assert s.ic_mean == pytest.approx(0.05)
    assert s.ic_std == pytest.approx(0.0)
    assert s.ic_positive_ratio == pytest.approx(1.0)
    assert s.n_periods == 20


def test_daily_ic_series_aligned() -> None:
    # Two dates, factor ranks match returns perfectly
    panel = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 2)] * 5 + [date(2024, 1, 3)] * 5,
            "factor": [1, 2, 3, 4, 5, 1, 2, 3, 4, 5],
            "ret": [0.01, 0.02, 0.03, 0.04, 0.05, 0.05, 0.04, 0.03, 0.02, 0.01],
        }
    )
    ics = daily_ic_series(panel, factor_col="factor", return_col="ret", min_names=3)
    assert ics.height == 2
    assert ics["ic"][0] == pytest.approx(1.0)
    assert ics["ic"][1] == pytest.approx(-1.0)


def test_quantile_monotonic_long_short() -> None:
    rows: list[dict[str, object]] = []
    for d_i, td in enumerate(_dates(30)):
        for sid in range(1, 21):
            f = float(sid)
            rows.append(
                {
                    "trade_date": td,
                    "security_id": sid,
                    "factor": f,
                    "ret": 0.001 * f + 0.0001 * d_i,
                }
            )
    panel = pl.DataFrame(rows)
    q = quantile_analysis(panel, factor_col="factor", return_col="ret", n_quantiles=5, min_names=10)
    assert q.monotonicity > 0.9
    assert q.long_short_return > 0
    assert q.quantile_returns[-1] > q.quantile_returns[0]


def test_synthetic_good_factor_positive_ic() -> None:
    panel = synthetic_eval_panel(n_dates=80, n_names=50, seed=7)
    result = evaluate_factor(
        panel,
        factor_code="good_factor",
        horizon=5,
        other_factor_cols=["noise_factor"],
        min_names=10,
        decay_horizons=(1, 5, 10),
    )
    assert result.n_ic_periods > 10
    assert result.ic_mean > 0.15
    assert result.monotonicity > 0.5
    assert "noise_factor" in result.correlations
    assert len(result.ic_decay) == 3
    md = render_factor_report(result)
    assert "good_factor" in md
    assert "IC mean" in md


def test_synthetic_noise_weaker_than_good() -> None:
    panel = synthetic_eval_panel(n_dates=80, n_names=50, seed=7)
    results = evaluate_factors(
        panel,
        ["good_factor", "noise_factor"],
        horizon=5,
        min_names=10,
        decay_horizons=(5,),
    )
    assert abs(results["good_factor"].ic_mean) > abs(results["noise_factor"].ic_mean)


def test_ic_decay_runs() -> None:
    panel = synthetic_eval_panel(n_dates=40, n_names=30, seed=1)
    hs, means = ic_decay(panel, factor_col="good_factor", horizons=(1, 5), min_names=5)
    assert hs == [1, 5]
    assert len(means) == 2


def test_passes_admission_fail_on_weak_ic() -> None:
    weak = FactorTestResult(
        factor_code="x",
        period=(date(2024, 1, 1), date(2024, 6, 1)),
        ic_mean=0.001,
        ic_std=0.05,
        icir=0.02,
        ic_t_stat=0.5,
        ic_p_value=0.6,
        ic_positive_ratio=0.5,
    )
    ok, notes = passes_admission(weak)
    assert ok is False
    assert any("ic_mean" in n for n in notes)


def test_write_factor_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    panel = synthetic_eval_panel(n_dates=40, n_names=25, seed=3)
    result = evaluate_factor(panel, factor_code="good_factor", min_names=8, decay_horizons=(5,))
    path = write_factor_report(result, tmp_path / "good_factor.md")
    text = path.read_text(encoding="utf-8")
    assert result.factor_code in text
    assert path.exists()


def test_attach_preserves_factor_column() -> None:
    dates = _dates(12)
    prices = pl.DataFrame(
        {
            "security_id": [1] * 12,
            "trade_date": dates,
            "close": list(range(100, 112)),
            "mom_20d": list(np.linspace(0, 1, 12)),
        }
    )
    out = attach_forward_returns(prices, horizons=[1, 5])
    assert "mom_20d" in out.columns
    assert "fwd_ret_1d" in out.columns
    assert "fwd_ret_5d" in out.columns
