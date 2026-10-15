"""Unit tests for L3 walk-forward Ridge / Logistic."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from quantagent.quant.features.base import FactorInput
from quantagent.quant.models.linear import run_l3_pipeline, walk_forward_scores
from quantagent.quant.training.walk_forward import (
    WalkForwardConfig,
    add_months,
    generate_folds,
)


def test_add_months_clamps_day() -> None:
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2023, 1, 31), 1) == date(2023, 2, 28)


def test_generate_folds_respects_embargo_and_panel_end() -> None:
    cfg = WalkForwardConfig(
        train_months=12,
        val_months=3,
        test_months=3,
        step_months=3,
        embargo_days=10,
    )
    folds = generate_folds(date(2020, 1, 1), date(2022, 6, 30), cfg)
    assert len(folds) >= 2
    f0 = folds[0]
    assert f0.val_start >= f0.train_end + timedelta(days=11)
    assert f0.test_start >= f0.val_end + timedelta(days=11)
    assert f0.test_end <= date(2022, 6, 30)
    # Contiguous steps: next train starts step_months later.
    assert folds[1].train_start == add_months(f0.train_start, cfg.step_months)


def _synthetic_rank_panel(
    *,
    n_dates: int = 900,
    n_names: int = 30,
    seed: int = 0,
) -> pl.DataFrame:
    """OHLCV-ish panel with two predictive rank features for L3 smoke."""
    rng = np.random.default_rng(seed)
    dates: list[date] = []
    d = date(2019, 1, 2)
    while len(dates) < n_dates:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)

    rows: list[dict[str, object]] = []
    for sid in range(1, n_names + 1):
        close = 100.0 + sid
        latent = float(rng.normal(0, 1))
        for i, td in enumerate(dates):
            # Feature ranks correlate with next-week return.
            f_pos = float(rng.uniform(0, 1))
            f_neg = float(rng.uniform(0, 1))
            shock = 0.02 * (f_pos - 0.5) - 0.015 * (f_neg - 0.5) + float(rng.normal(0, 0.01))
            close = max(1.0, close * (1.0 + shock))
            rows.append(
                {
                    "security_id": sid,
                    "trade_date": td,
                    "close": close,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "volume": 1_000_000.0,
                    "ep_ttm": f_pos,
                    "bp": f_neg,
                    "industry_code": f"I{sid % 5}",
                    "log_mktcap": 20.0 + latent,
                }
            )
    return pl.DataFrame(rows)


def test_walk_forward_scores_ridge_oos_only() -> None:
    panel = _synthetic_rank_panel()
    wf = WalkForwardConfig(
        train_months=24,
        val_months=3,
        test_months=3,
        step_months=3,
        embargo_days=10,
    )
    scores, diags, n_search = walk_forward_scores(
        panel,
        ["ep_ttm", "bp"],
        method="ridge",
        horizon=5,
        wf=wf,
    )
    assert not scores.is_empty()
    assert len(diags) >= 1
    assert n_search == len(diags) * 3  # 3 alphas per fold
    # Scores only on test windows.
    assert scores["score"].null_count() == 0


def test_run_l3_pipeline_synthetic_smoke() -> None:
    from quantagent.quant.evaluation.runner import synthetic_price_panel
    from quantagent.quant.features.registry import MVP_FACTOR_CODES

    prices = synthetic_price_panel(n_dates=900, n_names=25, seed=3)
    as_of = prices["trade_date"].max()
    assert isinstance(as_of, date)
    data = FactorInput(prices=prices, as_of=as_of)
    codes = list(MVP_FACTOR_CODES)[:2]
    results = run_l3_pipeline(
        data,
        codes=codes,
        methods=("ridge", "logistic"),
        transform=False,
        walk_forward=WalkForwardConfig(
            train_months=18,
            val_months=3,
            test_months=3,
            step_months=3,
            embargo_days=10,
        ),
    )
    assert "l3_ridge" in results and "l3_logistic" in results
    assert results["l3_ridge"].n_ic_periods > 0
    assert data.meta["l3"]["param_search_count"] > 0
