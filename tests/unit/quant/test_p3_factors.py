"""Unit tests for P3 factor expansion + L1 pipeline wiring."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from quantagent.quant.evaluation import (
    run_l1_pipeline,
    synthetic_l1_eval_panel,
    synthetic_price_panel,
)
from quantagent.quant.features import (
    ALL_FACTOR_CODES,
    MVP_FACTOR_CODES,
    P3_BATCH_CODES,
    FactorInput,
    build_factor_panel,
    compute_factors,
    get_factor,
)


def _dates(n: int, start: date = date(2023, 1, 3)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _ohlcv_panel(*, n: int = 80, security_id: int = 1, drift: float = 0.005) -> pl.DataFrame:
    dates = _dates(n)
    closes = [100.0 * ((1.0 + drift) ** i) for i in range(n)]
    opens = [closes[0], *closes[:-1]]
    return pl.DataFrame(
        {
            "security_id": [security_id] * n,
            "trade_date": dates,
            "open": opens,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000.0 + i * 1000.0 for i in range(n)],
            "amount": [1.0e8] * n,
            "turnover_rate": [0.02] * n,
            "pe_ttm": [12.0] * n,
            "pb": [2.0] * n,
            "ps_ttm": [4.0] * n,
        }
    )


def _input(prices: pl.DataFrame) -> FactorInput:
    as_of = prices["trade_date"].max()
    assert isinstance(as_of, date)
    return FactorInput(prices=prices, as_of=as_of)


def test_registry_mvp_unchanged_and_p3_expanded() -> None:
    assert len(MVP_FACTOR_CODES) == 8
    assert len(P3_BATCH_CODES) == 25
    assert len(ALL_FACTOR_CODES) == 33
    assert set(MVP_FACTOR_CODES).isdisjoint(P3_BATCH_CODES)
    assert set(MVP_FACTOR_CODES) | set(P3_BATCH_CODES) == set(ALL_FACTOR_CODES)


def test_mom_5d_and_ex1w() -> None:
    prices = _ohlcv_panel(n=30, drift=0.01)
    mom5 = get_factor("mom_5d").compute(_input(prices))
    expected = (1.01**5) - 1.0
    assert abs(float(mom5[-1]) - expected) < 1e-9

    ex = get_factor("mom_20d_ex1w").compute(_input(prices))
    # close_{t-5}/close_{t-20}-1 = (1.01**15)-1
    assert abs(float(ex[-1]) - ((1.01**15) - 1.0)) < 1e-9


def test_rev_1d_and_overnight_intraday() -> None:
    prices = _ohlcv_panel(n=10, drift=0.02)
    rev1 = get_factor("rev_1d").compute(_input(prices))
    day_ret = prices["close"][-1] / prices["close"][-2] - 1.0
    assert abs(float(rev1[-1]) + day_ret) < 1e-12

    overnight = get_factor("rev_overnight").compute(_input(prices))
    # open_t / close_{t-1} - 1; our panel sets open_t = close_{t-1}
    assert abs(float(overnight[-1])) < 1e-12

    intraday = get_factor("rev_intraday").compute(_input(prices))
    assert abs(float(intraday[-1]) - day_ret) < 1e-12


def test_vol_ratio_and_max_dd() -> None:
    prices = _ohlcv_panel(n=80, drift=0.0)
    # inject a drawdown mid-sample so 20d vol >> trailing calm 60d tail
    closes = prices["close"].to_list()
    closes[70] = closes[69] * 0.8
    prices = prices.with_columns(pl.Series("close", closes))
    ratio = get_factor("vol_ratio_20_60").compute(_input(prices))
    assert ratio[-1] is not None
    assert float(ratio[-1]) > 1.0

    dd = get_factor("max_dd_60d").compute(_input(prices))
    assert dd[70] is not None
    assert float(dd[70]) < -0.15


def test_value_bp_sp() -> None:
    prices = _ohlcv_panel(n=5)
    bp = get_factor("bp").compute(_input(prices))
    sp = get_factor("sp_ttm").compute(_input(prices))
    assert abs(float(bp[-1]) - 0.5) < 1e-12
    assert abs(float(sp[-1]) - 0.25) < 1e-12


def test_trend_slope_positive_on_uptrend() -> None:
    prices = _ohlcv_panel(n=80, drift=0.01)
    slope = get_factor("trend_slope_60d").compute(_input(prices))
    r2 = get_factor("trend_r2_60d").compute(_input(prices))
    assert slope[-1] is not None and float(slope[-1]) > 0
    assert r2[-1] is not None and float(r2[-1]) > 0.9


def test_compute_all_p3_batch_on_ohlcv() -> None:
    # noisy multi-name panel so beta / rel_str market moments are defined
    panel = synthetic_price_panel(n_dates=280, n_names=8, seed=3)
    out = compute_factors(_input(panel), codes=list(P3_BATCH_CODES))
    assert out.height == panel.height
    for code in P3_BATCH_CODES:
        assert code in out.columns
        # warm-up nulls ok; every factor must produce some finite values
        assert out[code].null_count() < out.height, code


def test_build_factor_panel_keeps_close() -> None:
    prices = _ohlcv_panel(n=40)
    panel = build_factor_panel(_input(prices), codes=["mom_5d", "rev_1d"])
    assert "close" in panel.columns
    assert "mom_5d" in panel.columns


def test_run_l1_pipeline_synthetic() -> None:
    prices = synthetic_price_panel(n_dates=100, n_names=20, seed=1)
    as_of = prices["trade_date"].max()
    assert isinstance(as_of, date)
    results = run_l1_pipeline(
        FactorInput(prices=prices, as_of=as_of),
        codes=["mom_20d", "rev_5d", "vol_20d"],
        horizon=5,
        decay_horizons=(5,),
        min_names=8,
    )
    assert set(results) == {"mom_20d", "rev_5d", "vol_20d"}
    for r in results.values():
        assert r.n_ic_periods > 0
        assert r.admission_notes


def test_synthetic_l1_eval_panel_has_all_codes() -> None:
    panel = synthetic_l1_eval_panel(n_dates=90, n_names=15, seed=2, codes=list(P3_BATCH_CODES)[:5])
    for code in list(P3_BATCH_CODES)[:5]:
        assert code in panel.columns
    assert "close" in panel.columns


def test_unknown_still_errors() -> None:
    with pytest.raises(KeyError, match="unknown factor"):
        get_factor("not_a_factor")
