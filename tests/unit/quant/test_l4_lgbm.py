"""Unit tests for L4 walk-forward LightGBM."""

from __future__ import annotations

from datetime import date

from quantagent.quant.features.base import FactorInput
from quantagent.quant.models.gbdt import (
    L4FoldDiag,
    importance_stability,
    run_l4_pipeline,
)
from quantagent.quant.training.walk_forward import WalkForwardConfig


def test_importance_stability_perfect_rank() -> None:
    cols = ["a", "b", "c"]
    d0 = L4FoldDiag(
        fold_id=0,
        best_preset=0,
        best_rounds=10,
        n_train=1,
        n_val=1,
        n_test=1,
        test_start=date(2024, 1, 1),
        test_end=date(2024, 6, 1),
        val_ic=0.1,
        importance={"a": 3.0, "b": 2.0, "c": 1.0},
    )
    d1 = L4FoldDiag(
        fold_id=1,
        best_preset=1,
        best_rounds=12,
        n_train=1,
        n_val=1,
        n_test=1,
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 1),
        val_ic=0.1,
        importance={"a": 30.0, "b": 20.0, "c": 10.0},
    )
    assert importance_stability([d0, d1], cols) == 1.0


def test_run_l4_pipeline_synthetic_smoke() -> None:
    from quantagent.quant.evaluation.runner import synthetic_price_panel
    from quantagent.quant.features.registry import MVP_FACTOR_CODES

    prices = synthetic_price_panel(n_dates=900, n_names=25, seed=3)
    as_of = prices["trade_date"].max()
    assert isinstance(as_of, date)
    data = FactorInput(prices=prices, as_of=as_of)
    codes = list(MVP_FACTOR_CODES)[:2]
    results = run_l4_pipeline(
        data,
        codes=codes,
        transform=False,
        compare_l2=True,
        walk_forward=WalkForwardConfig(
            train_months=18,
            val_months=3,
            test_months=3,
            step_months=3,
            embargo_days=10,
        ),
    )
    assert "l4_lgbm" in results
    assert "l2_equal_oos" in results
    assert results["l4_lgbm"].n_ic_periods > 0
    meta = data.meta["l4"]
    assert meta["param_search_count"] == meta["n_folds"] * 3
    assert "beats_l2_oos" in meta
