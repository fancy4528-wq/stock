"""L4: walk-forward LightGBM on L1-admitted factor ranks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.stats import spearmanr

from quantagent.quant.evaluation.runner import evaluate_factor
from quantagent.quant.evaluation.types import FactorTestResult
from quantagent.quant.features.base import FactorInput, entity_col
from quantagent.quant.labels.targets import attach_forward_returns, forward_return_col
from quantagent.quant.models.baseline import (
    CSI300_L1_ADMITTED_5Y,
    build_l2_panel,
    combine_equal_weight,
    estimate_ic_means,
)
from quantagent.quant.training.holdout_guard import HoldoutGuard
from quantagent.quant.training.walk_forward import (
    WalkForwardConfig,
    WalkForwardFold,
    generate_folds,
)

COMBO_LGBM: Final[str] = "l4_lgbm"
COMBO_L2_OOS: Final[str] = "l2_equal_oos"

# ≤6 presets × folds keeps Gate 3 param_search_count well under 20 for 3 folds.
LGBM_PRESETS: Final[tuple[dict[str, Any], ...]] = (
    {
        "num_leaves": 31,
        "learning_rate": 0.05,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 1.0,
    },
    {
        "num_leaves": 15,
        "learning_rate": 0.05,
        "min_data_in_leaf": 400,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.7,
        "bagging_freq": 1,
        "lambda_l2": 5.0,
    },
    {
        "num_leaves": 63,
        "learning_rate": 0.03,
        "min_data_in_leaf": 100,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "lambda_l2": 0.5,
    },
)

NUM_BOOST_ROUND: Final[int] = 300
EARLY_STOPPING: Final[int] = 30


@dataclass
class L4FoldDiag:
    fold_id: int
    best_preset: int
    best_rounds: int
    n_train: int
    n_val: int
    n_test: int
    test_start: date
    test_end: date
    val_ic: float
    importance: dict[str, float] = field(default_factory=dict)


def _xy(
    frame: pl.DataFrame,
    feature_cols: list[str],
    label_col: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Features keep NaN (LightGBM native); drop rows with null labels."""
    feats = (
        frame.select(feature_cols)
        .with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in feature_cols])
        .to_numpy()
    )
    y = np.asarray(frame[label_col].to_numpy(), dtype=np.float64)
    ok = np.isfinite(y)
    return feats, y, ok


def _val_spearman_ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 10:
        return float("-inf")
    corr, _ = spearmanr(y_pred, y_true)
    if corr is None or not np.isfinite(corr):
        return float("-inf")
    return float(corr)


def _fit_lgbm_fold(
    x_tr: np.ndarray,
    y_tr: np.ndarray,
    x_va: np.ndarray,
    y_va: np.ndarray,
    feature_cols: list[str],
) -> tuple[lgb.Booster, int, int, float, dict[str, float], int]:
    """Select among presets by val Spearman; return booster + diagnostics."""
    best_booster: lgb.Booster | None = None
    best_preset = 0
    best_rounds = 1
    best_ic = float("-inf")
    searches = 0

    train_set = lgb.Dataset(x_tr, label=y_tr, feature_name=feature_cols, free_raw_data=False)
    val_set = lgb.Dataset(
        x_va, label=y_va, reference=train_set, feature_name=feature_cols, free_raw_data=False
    )

    for i, preset in enumerate(LGBM_PRESETS):
        searches += 1
        params = {
            "objective": "regression",
            "metric": "l2",
            "verbosity": -1,
            "seed": 42,
            "num_threads": 0,
            # Allow per-preset min_data_in_leaf without Dataset rebuild warnings.
            "feature_pre_filter": False,
            **preset,
        }
        callbacks = [
            lgb.early_stopping(EARLY_STOPPING, verbose=False),
            lgb.log_evaluation(period=0),
        ]
        booster = lgb.train(
            params,
            train_set,
            num_boost_round=NUM_BOOST_ROUND,
            valid_sets=[val_set],
            valid_names=["val"],
            callbacks=callbacks,
        )
        pred = booster.predict(x_va, num_iteration=booster.best_iteration)
        ic = _val_spearman_ic(y_va, np.asarray(pred, dtype=np.float64))
        if ic > best_ic:
            best_ic = ic
            best_booster = booster
            best_preset = i
            best_rounds = int(booster.best_iteration or 1)

    assert best_booster is not None
    gain = best_booster.feature_importance(importance_type="gain")
    importance = {
        c: float(g) for c, g in zip(feature_cols, gain, strict=True)
    }
    return best_booster, best_preset, best_rounds, best_ic, importance, searches


def _predict_lgbm_fold(
    panel: pl.DataFrame,
    fold: WalkForwardFold,
    feature_cols: list[str],
    label_col: str,
    date_col: str = "trade_date",
) -> tuple[pl.DataFrame, L4FoldDiag, int]:
    ent = entity_col(panel)
    tr = panel.filter(
        (pl.col(date_col) >= fold.train_start) & (pl.col(date_col) <= fold.train_end)
    )
    va = panel.filter(
        (pl.col(date_col) >= fold.val_start) & (pl.col(date_col) <= fold.val_end)
    )
    te = panel.filter(
        (pl.col(date_col) >= fold.test_start) & (pl.col(date_col) <= fold.test_end)
    )

    x_tr, y_tr, ok_tr = _xy(tr, feature_cols, label_col)
    x_va, y_va, ok_va = _xy(va, feature_cols, label_col)
    x_te, _, ok_te = _xy(te, feature_cols, label_col)
    x_tr, y_tr = x_tr[ok_tr], y_tr[ok_tr]
    x_va, y_va = x_va[ok_va], y_va[ok_va]

    if len(y_tr) < 100 or len(y_va) < 30:
        raise ValueError(
            f"fold {fold.fold_id} lgbm: insufficient samples "
            f"(train={len(y_tr)}, val={len(y_va)})"
        )

    result = _fit_lgbm_fold(x_tr, y_tr, x_va, y_va, feature_cols)
    booster, best_preset, best_rounds, val_ic, importance, searches = result

    scores = np.full(te.height, np.nan, dtype=np.float64)
    if ok_te.any():
        scores[ok_te] = booster.predict(
            x_te[ok_te], num_iteration=booster.best_iteration
        )

    out = te.select([ent, date_col]).with_columns(
        pl.Series("score", scores).cast(pl.Float64)
    )
    diag = L4FoldDiag(
        fold_id=fold.fold_id,
        best_preset=best_preset,
        best_rounds=best_rounds,
        n_train=int(len(y_tr)),
        n_val=int(len(y_va)),
        n_test=int(ok_te.sum()),
        test_start=fold.test_start,
        test_end=fold.test_end,
        val_ic=float(val_ic),
        importance=importance,
    )
    return out, diag, searches


def importance_stability(diags: list[L4FoldDiag], feature_cols: list[str]) -> float:
    """Mean pairwise Spearman correlation of gain-importance across folds."""
    if len(diags) < 2:
        return float("nan")
    mats = []
    for d in diags:
        mats.append(np.array([d.importance.get(c, 0.0) for c in feature_cols], dtype=float))
    corrs: list[float] = []
    for i in range(len(mats)):
        for j in range(i + 1, len(mats)):
            if np.allclose(mats[i], mats[i][0]) or np.allclose(mats[j], mats[j][0]):
                continue
            corr, _ = spearmanr(mats[i], mats[j])
            if corr is not None and np.isfinite(corr):
                corrs.append(float(corr))
    if not corrs:
        return float("nan")
    return float(np.mean(corrs))


def walk_forward_lgbm_scores(
    panel: pl.DataFrame,
    feature_cols: list[str],
    *,
    horizon: int = 5,
    wf: WalkForwardConfig | None = None,
    guard: HoldoutGuard | None = None,
    date_col: str = "trade_date",
    price_col: str = "close",
) -> tuple[pl.DataFrame, list[L4FoldDiag], int, list[WalkForwardFold]]:
    labeled = attach_forward_returns(panel, horizons=[horizon], price_col=price_col)
    label_col = forward_return_col(horizon)
    dates = labeled[date_col]
    panel_start = dates.min()
    panel_end = dates.max()
    assert isinstance(panel_start, date) and isinstance(panel_end, date)

    folds = generate_folds(panel_start, panel_end, wf, guard=guard)
    if not folds:
        raise ValueError(
            f"no walk-forward folds in [{panel_start}, {panel_end}] "
            f"with config {wf or WalkForwardConfig()}"
        )

    ent = entity_col(labeled)
    pieces: list[pl.DataFrame] = []
    diags: list[L4FoldDiag] = []
    total_searches = 0
    for fold in folds:
        part, diag, n_search = _predict_lgbm_fold(
            labeled, fold, feature_cols, label_col, date_col=date_col
        )
        pieces.append(part)
        diags.append(diag)
        total_searches += n_search
        print(
            f"l4/lgbm: fold={fold.fold_id} "
            f"train={fold.train_start}..{fold.train_end} "
            f"val={fold.val_start}..{fold.val_end} "
            f"test={fold.test_start}..{fold.test_end} "
            f"preset={diag.best_preset} rounds={diag.best_rounds} "
            f"val_ic={diag.val_ic:+.4f} n_test={diag.n_test}",
            flush=True,
        )

    scores = pl.concat(pieces).unique(subset=[ent, date_col], keep="last")
    return scores, diags, total_searches, folds


def walk_forward_l2_equal_oos(
    panel: pl.DataFrame,
    feature_cols: list[str],
    folds: list[WalkForwardFold],
    *,
    horizon: int = 5,
    date_col: str = "trade_date",
    min_names: int = 5,
) -> pl.DataFrame:
    """Per-fold L2 equal-weight using train-window IC signs; stitch test scores."""
    ent = entity_col(panel)
    pieces: list[pl.DataFrame] = []
    for fold in folds:
        train = panel.filter(
            (pl.col(date_col) >= fold.train_start) & (pl.col(date_col) <= fold.train_end)
        )
        ic_means = estimate_ic_means(
            train, feature_cols, horizon=horizon, min_names=min_names
        )
        scored = combine_equal_weight(panel, feature_cols, ic_means, out_col="score")
        te = scored.filter(
            (pl.col(date_col) >= fold.test_start) & (pl.col(date_col) <= fold.test_end)
        ).select([ent, date_col, "score"])
        pieces.append(te)
        print(
            f"l4/l2_oos: fold={fold.fold_id} "
            f"test={fold.test_start}..{fold.test_end} "
            f"ic_signs="
            + ",".join(f"{k}:{v:+.3f}" for k, v in ic_means.items()),
            flush=True,
        )
    return pl.concat(pieces).unique(subset=[ent, date_col], keep="last")


def run_l4_pipeline(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
    *,
    horizon: int = 5,
    n_quantiles: int = 5,
    decay_horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    min_names: int = 5,
    transform: bool = True,
    walk_forward: WalkForwardConfig | None = None,
    guard: HoldoutGuard | None = None,
    compare_l2: bool = True,
) -> dict[str, FactorTestResult]:
    """Build L4 LightGBM OOS scores (+ optional fair L2 OOS) and evaluate."""
    selected = list(codes) if codes is not None else list(CSI300_L1_ADMITTED_5Y)
    if not selected:
        raise ValueError("L4 requires at least one component factor")

    wf = walk_forward or WalkForwardConfig()
    panel = build_l2_panel(data, selected, transform=transform)
    for c in selected:
        if c not in panel.columns:
            raise KeyError(f"factor column missing after panel build: {c}")

    print(f"l4: walk-forward LightGBM on {len(selected)} factors", flush=True)
    scores, diags, n_search, folds = walk_forward_lgbm_scores(
        panel,
        selected,
        horizon=horizon,
        wf=wf,
        guard=guard,
    )
    stab = importance_stability(diags, selected)
    print(
        f"l4: importance_stability={stab:+.3f} "
        f"folds={len(diags)} param_search_count={n_search}",
        flush=True,
    )

    ent = entity_col(panel)
    score_panel = panel.join(
        scores.rename({"score": COMBO_LGBM}),
        on=[ent, "trade_date"],
        how="left",
    )

    results: dict[str, FactorTestResult] = {}
    print(f"l4: evaluating {COMBO_LGBM}", flush=True)
    results[COMBO_LGBM] = evaluate_factor(
        score_panel,
        factor_code=COMBO_LGBM,
        factor_col=COMBO_LGBM,
        horizon=horizon,
        n_quantiles=n_quantiles,
        decay_horizons=decay_horizons,
        other_factor_cols=selected,
        min_names=min_names,
    )
    note = (
        f"L4 LightGBM walk-forward OOS "
        f"(train={wf.train_months}m val={wf.val_months}m "
        f"test={wf.test_months}m step={wf.step_months}m "
        f"embargo={wf.embargo_days}d; importance_stability={stab:+.3f}; "
        f"not L1 admission)"
    )
    results[COMBO_LGBM].admission_notes = [note, *results[COMBO_LGBM].admission_notes]

    l2_icir: float | None = None
    beats_l2 = False
    if compare_l2:
        print("l4: walk-forward L2 equal OOS (fair baseline)", flush=True)
        l2_scores = walk_forward_l2_equal_oos(
            panel, selected, folds, horizon=horizon, min_names=min_names
        )
        score_panel = score_panel.join(
            l2_scores.rename({"score": COMBO_L2_OOS}),
            on=[ent, "trade_date"],
            how="left",
        )
        results[COMBO_L2_OOS] = evaluate_factor(
            score_panel,
            factor_code=COMBO_L2_OOS,
            factor_col=COMBO_L2_OOS,
            horizon=horizon,
            n_quantiles=n_quantiles,
            decay_horizons=decay_horizons,
            other_factor_cols=selected,
            min_names=min_names,
        )
        results[COMBO_L2_OOS].admission_notes = [
            "Walk-forward L2 equal-weight OOS (train IC signs; fair L4 baseline)",
            *results[COMBO_L2_OOS].admission_notes,
        ]
        l2_icir = float(results[COMBO_L2_OOS].icir)
        l4_icir = float(results[COMBO_LGBM].icir)
        beats_l2 = l4_icir > l2_icir
        gate_note = (
            f"Gate3 L4 vs L2 OOS: l4_icir={l4_icir:+.3f} "
            f"l2_equal_oos_icir={l2_icir:+.3f} → "
            f"{'PASS (beats L2)' if beats_l2 else 'FAIL (does not beat L2)'}"
        )
        results[COMBO_LGBM].admission_notes = [
            gate_note,
            *results[COMBO_LGBM].admission_notes,
        ]
        print(f"l4: {gate_note}", flush=True)

    mean_importance: dict[str, float] = {c: 0.0 for c in selected}
    if diags:
        for c in selected:
            mean_importance[c] = float(
                np.mean([d.importance.get(c, 0.0) for d in diags])
            )

    data.meta["l4"] = {
        "components": selected,
        "n_folds": len(diags),
        "param_search_count": n_search,
        "importance_stability": stab,
        "mean_importance": mean_importance,
        "beats_l2_oos": beats_l2,
        "l2_equal_oos_icir": l2_icir,
        "l4_icir": float(results[COMBO_LGBM].icir),
        "walk_forward": {
            "train_months": wf.train_months,
            "val_months": wf.val_months,
            "test_months": wf.test_months,
            "step_months": wf.step_months,
            "embargo_days": wf.embargo_days,
            "holdout_start": (
                wf.holdout_start.isoformat() if wf.holdout_start else None
            ),
        },
        "folds": [
            {
                "fold_id": d.fold_id,
                "best_preset": d.best_preset,
                "best_rounds": d.best_rounds,
                "n_train": d.n_train,
                "n_val": d.n_val,
                "n_test": d.n_test,
                "test_start": d.test_start.isoformat(),
                "test_end": d.test_end.isoformat(),
                "val_ic": d.val_ic,
                "importance": d.importance,
            }
            for d in diags
        ],
    }
    return results
