"""Unit tests for cross-sectional factor transforms."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from quantagent.quant.features.base import FactorInput
from quantagent.quant.features.transform import (
    TransformConfig,
    attach_cs_covariates,
    estimate_log_mktcap,
    neutralize,
    rank_pct,
    transform_cross_section,
    winsorize_mad,
)


def test_winsorize_mad_clips_outlier() -> None:
    s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 100.0])
    out = winsorize_mad(s, n=3.0)
    assert float(out.max()) < 100.0  # type: ignore[arg-type]
    assert float(out.min()) >= 1.0  # type: ignore[arg-type]


def test_rank_pct_bounds_and_ties() -> None:
    s = pl.Series("x", [10.0, 20.0, 20.0, 40.0])
    r = rank_pct(s)
    assert float(r.min()) == pytest.approx(0.0)  # type: ignore[arg-type]
    assert float(r.max()) == pytest.approx(1.0)  # type: ignore[arg-type]
    # ties share the average rank → same pct
    assert float(r[1]) == pytest.approx(float(r[2]))


def test_rank_pct_treats_nan_as_null() -> None:
    """NaN must not share one percentile (would collapse cross-factor corr)."""
    s = pl.Series("x", [1.0, float("nan"), 3.0, float("nan"), 5.0])
    r = rank_pct(s)
    assert r.null_count() == 2
    finite = [float(v) for v in r.to_list() if v is not None]
    assert finite == pytest.approx([0.0, 0.5, 1.0])


def test_neutralize_missing_industry_is_null_not_nan() -> None:
    industry = pl.Series("ind", ["A", None, "B", None, "B"])
    factor = pl.Series("f", [1.0, 2.0, 3.0, 4.0, 5.0])
    log_mc = pl.Series("mc", [1.0, 1.1, 1.2, 1.3, 1.4])
    resid = neutralize(factor, industry=industry, log_mktcap=log_mc)
    assert resid.null_count() == 2
    assert resid.dtype == pl.Float64
    # No NaN masquerading as values (Polars null_count ignores NaN).
    assert int(np.isnan(resid.drop_nulls().to_numpy()).sum()) == 0


def test_neutralize_removes_industry_mean() -> None:
    # Factor = industry effect + noise; residual should be near zero mean per industry.
    industry = pl.Series("ind", ["A", "A", "B", "B", "B", "C"])
    factor = pl.Series("f", [10.0, 12.0, -5.0, -3.0, -4.0, 1.0])
    resid = neutralize(factor, industry=industry, log_mktcap=None)
    # Within industry A, residual mean ≈ 0
    a = resid.to_numpy()[:2]
    assert abs(float(np.nanmean(a))) < 1e-9


def test_neutralize_mktcap_only() -> None:
    rng = np.random.default_rng(0)
    log_mc = pl.Series("mc", rng.normal(size=40).tolist())
    factor = pl.Series("f", (2.0 * log_mc.to_numpy() + rng.normal(scale=0.01, size=40)).tolist())
    resid = neutralize(factor, industry=None, log_mktcap=log_mc)
    # Residual should be much smaller variance than raw factor.
    assert float(np.nanstd(resid.to_numpy())) < 0.5 * float(np.nanstd(factor.to_numpy()))


def test_estimate_log_mktcap_proxy() -> None:
    df = pl.DataFrame(
        {
            "close": [10.0, 20.0],
            "volume": [1_000_000.0, 2_000_000.0],
            "turnover_rate": [0.02, 0.01],
        }
    )
    log_mc = estimate_log_mktcap(df)
    # close*volume/turnover = 10*1e6/0.02 = 5e8
    assert float(log_mc[0]) == pytest.approx(np.log(5e8))


def test_transform_cross_section_per_date() -> None:
    dates = [date(2024, 1, 2), date(2024, 1, 3)]
    rows: list[dict[str, object]] = []
    for td in dates:
        for sid in range(1, 11):
            rows.append(
                {
                    "security_id": sid,
                    "trade_date": td,
                    "close": 100.0 + sid,
                    "volume": 1_000_000.0,
                    "turnover_rate": 0.02,
                    "industry_code": f"I{sid % 3}",
                    "good_factor": float(sid) + (0.0 if td.day == 2 else 10.0),
                }
            )
    panel = pl.DataFrame(rows)
    panel = panel.with_columns(estimate_log_mktcap(panel))
    out = transform_cross_section(
        panel,
        ["good_factor"],
        config=TransformConfig(enabled=True, mad_n=3.0),
    )
    # Per date, transformed factor is a rank in [0, 1]
    for td in dates:
        sub = out.filter(pl.col("trade_date") == td)["good_factor"]
        assert float(sub.min()) == pytest.approx(0.0)  # type: ignore[arg-type]
        assert float(sub.max()) == pytest.approx(1.0)  # type: ignore[arg-type]


def test_attach_cs_covariates_joins_industry() -> None:
    prices = pl.DataFrame(
        {
            "security_id": [1, 2, 1, 2],
            "trade_date": [date(2024, 1, 2)] * 2 + [date(2024, 1, 3)] * 2,
            "close": [10.0, 20.0, 11.0, 21.0],
            "volume": [1e6, 2e6, 1e6, 2e6],
            "turnover_rate": [0.02, 0.02, 0.02, 0.02],
            "mom": [0.1, -0.1, 0.2, -0.2],
        }
    )
    industry = pl.DataFrame(
        {
            "security_id": [1, 2],
            "industry_code": ["801780", "801790"],
            "level": [1, 1],
        }
    )
    data = FactorInput(prices=prices, industry=industry, as_of=date(2024, 1, 3))
    out = attach_cs_covariates(prices, data)
    assert "industry_code" in out.columns
    assert "log_mktcap" in out.columns
    assert out.filter(pl.col("security_id") == 1)["industry_code"].unique().to_list() == [
        "801780"
    ]


def test_transform_disabled_is_noop() -> None:
    d0 = date(2024, 1, 2)
    panel = pl.DataFrame(
        {
            "security_id": [1, 2, 3],
            "trade_date": [d0, d0, d0],
            "f": [1.0, 2.0, 3.0],
        }
    )
    out = transform_cross_section(
        panel, ["f"], config=TransformConfig(enabled=False)
    )
    assert out["f"].to_list() == [1.0, 2.0, 3.0]
