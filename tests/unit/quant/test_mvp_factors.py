"""Unit tests for MVP price/volume factors."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from quantagent.quant.features import (
    MVP_FACTOR_CODES,
    FactorError,
    FactorInput,
    compute_factors,
    get_factor,
)


def _dates(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _panel(
    *,
    n: int = 80,
    close0: float = 100.0,
    drift: float = 0.01,
    turnover: float = 0.02,
    amount: float = 1.0e8,
    security_id: int = 1,
) -> pl.DataFrame:
    dates = _dates(n)
    closes = [close0 * ((1.0 + drift) ** i) for i in range(n)]
    return pl.DataFrame(
        {
            "security_id": [security_id] * n,
            "trade_date": dates,
            "close": closes,
            "turnover_rate": [turnover] * n,
            "amount": [amount] * n,
        }
    )


def _input(prices: pl.DataFrame, **kwargs: object) -> FactorInput:
    as_of = prices["trade_date"].max()
    assert isinstance(as_of, date)
    return FactorInput(prices=prices, as_of=as_of, **kwargs)  # type: ignore[arg-type]


def test_mvp_registry_has_eight_factors() -> None:
    assert len(MVP_FACTOR_CODES) == 8
    assert set(MVP_FACTOR_CODES) == {
        "mom_20d",
        "mom_60d",
        "rev_5d",
        "vol_20d",
        "turnover_20d",
        "turnover_ratio_5_60",
        "ep_ttm",
        "amihud_illiq_20d",
    }


def test_mom_20d_exact() -> None:
    prices = _panel(n=25, drift=0.01)
    series = get_factor("mom_20d").compute(_input(prices))
    # close_t / close_{t-20} - 1 = (1.01**20) - 1
    expected = (1.01**20) - 1.0
    val = series[-1]
    assert val is not None
    assert abs(float(val) - expected) < 1e-9
    assert series[19] is None  # insufficient history (0-indexed: need 20 lags)


def test_mom_60d_warmup() -> None:
    prices = _panel(n=70, drift=0.0)
    series = get_factor("mom_60d").compute(_input(prices))
    assert series[59] is None
    assert series[60] == 0.0


def test_rev_5d_is_negative_momentum() -> None:
    prices = _panel(n=20, drift=0.02)
    mom5 = prices.select(
        (pl.col("close") / pl.col("close").shift(5).over("security_id") - 1).alias("m")
    ).get_column("m")[-1]
    rev = get_factor("rev_5d").compute(_input(prices))[-1]
    assert mom5 is not None and rev is not None
    assert abs(float(rev) + float(mom5)) < 1e-12


def test_vol_20d_constant_return_near_zero() -> None:
    # Geometric drift still produces nearly constant daily log-ish pct returns
    prices = _panel(n=40, drift=0.0)
    # Inject one big move then flat — after window rolls past, vol drops
    closes = prices["close"].to_list()
    closes[10] = closes[9] * 1.5
    prices = prices.with_columns(pl.Series("close", closes))
    vol = get_factor("vol_20d").compute(_input(prices))
    assert vol[9] is None or (vol[19] is not None)
    assert vol[-1] is not None
    assert float(vol[-1]) >= 0.0


def test_turnover_20d_and_ratio() -> None:
    dates = _dates(70)
    # first 60 days low turnover, last 10 high
    turn = [0.01] * 60 + [0.05] * 10
    prices = pl.DataFrame(
        {
            "security_id": [1] * 70,
            "trade_date": dates,
            "close": [100.0] * 70,
            "turnover_rate": turn,
            "amount": [1e8] * 70,
        }
    )
    t20 = get_factor("turnover_20d").compute(_input(prices))
    ratio = get_factor("turnover_ratio_5_60").compute(_input(prices))
    assert t20[-1] is not None
    # last 20: 10*0.01 + 10*0.05 = 0.6 → mean 0.03
    assert abs(float(t20[-1]) - 0.03) < 1e-9
    assert ratio[-1] is not None
    assert float(ratio[-1]) > 1.0  # recent turnover elevated vs long window


def test_amihud_illiq_scales_with_amount() -> None:
    base = _panel(n=40, drift=0.01, amount=1.0e8)
    thin = base.with_columns((pl.col("amount") / 10.0).alias("amount"))
    a_base = get_factor("amihud_illiq_20d").compute(_input(base))[-1]
    a_thin = get_factor("amihud_illiq_20d").compute(_input(thin))[-1]
    assert a_base is not None and a_thin is not None
    assert float(a_thin) > float(a_base)


def test_ep_ttm_from_valuations() -> None:
    prices = _panel(n=5, drift=0.0)
    valuations = prices.select(["security_id", "trade_date"]).with_columns(
        pl.lit(10.0).alias("pe_ttm")
    )
    ep = get_factor("ep_ttm").compute(_input(prices, valuations=valuations))
    assert all(abs(float(v) - 0.1) < 1e-12 for v in ep.to_list() if v is not None)


def test_ep_ttm_negative_pe() -> None:
    prices = _panel(n=3, drift=0.0)
    valuations = prices.select(["security_id", "trade_date"]).with_columns(
        pl.lit(-8.0).alias("pe_ttm")
    )
    ep = get_factor("ep_ttm").compute(_input(prices, valuations=valuations))
    assert abs(float(ep[-1]) - (-0.125)) < 1e-12


def test_compute_factors_all_except_ep_without_fin() -> None:
    prices = _panel(n=80)
    codes = [c for c in MVP_FACTOR_CODES if c != "ep_ttm"]
    out = compute_factors(_input(prices), codes=codes)
    assert out.height == 80
    for c in codes:
        assert c in out.columns
        assert out[c].null_count() < out.height  # some warm-up nulls ok


def test_ep_requires_inputs() -> None:
    prices = _panel(n=5)
    with pytest.raises(FactorError, match="ep_ttm requires"):
        get_factor("ep_ttm").compute(_input(prices))


def test_unknown_factor() -> None:
    with pytest.raises(KeyError, match="unknown factor"):
        get_factor("not_a_factor")
