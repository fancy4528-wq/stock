"""L3: walk-forward Ridge / Logistic on L1-admitted factor ranks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Final, Literal

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import mean_squared_error

from quantagent.quant.evaluation.runner import evaluate_factor
from quantagent.quant.evaluation.types import FactorTestResult
from quantagent.quant.features.base import FactorInput, entity_col
from quantagent.quant.labels.targets import attach_forward_returns, forward_return_col
from quantagent.quant.models.baseline import CSI300_L1_ADMITTED_5Y, build_l2_panel
from quantagent.quant.training.holdout_guard import HoldoutGuard
from quantagent.quant.training.walk_forward import (
    WalkForwardConfig,
    WalkForwardFold,
    generate_folds,
)

L3Method = Literal["ridge", "logistic"]

COMBO_RIDGE: Final[str] = "l3_ridge"
COMBO_LOGISTIC: Final[str] = "l3_logistic"

# Small fixed grids — keep Gate 3 param_search_count well under 20.
RIDGE_ALPHAS: Final[tuple[float, ...]] = (0.1, 1.0, 10.0)
LOGISTIC_CS: Final[tuple[float, ...]] = (0.1, 1.0, 10.0)


@dataclass
class L3FoldDiag:
    fold_id: int
    method: str
    best_param: float
    n_train: int
    n_val: int
    n_test: int
    test_start: date
    test_end: date
    coef: dict[str, float] = field(default_factory=dict)


@dataclass
class L3RunMeta:
    methods: list[str]
    components: list[str]
    n_folds: int
    param_search_count: int
    folds: list[L3FoldDiag] = field(default_factory=list)
    walk_forward: dict[str, int | None] = field(default_factory=dict)


def _xy(
    frame: pl.DataFrame,
    feature_cols: list[str],
    label_col: str,
    *,
    binary: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (X, y, row_ok_mask) with nulls dropped; ranks filled to 0.5."""
    feats = frame.select(feature_cols).fill_null(0.5).to_numpy().astype(np.float64)
    y_raw = frame[label_col].to_numpy()
    y = np.asarray(y_raw, dtype=np.float64)
    ok = np.isfinite(y) & np.all(np.isfinite(feats), axis=1)
    if binary:
        # Cross-sectional median within the already-sliced frame (caller scopes dates).
        med = float(np.nanmedian(y[ok])) if ok.any() else 0.0
        y_bin = (y > med).astype(np.float64)
        y_bin[~ok] = np.nan
        return feats, y_bin, ok
    return feats, y, ok


def _cs_binary_label(panel: pl.DataFrame, label_col: str, date_col: str) -> pl.DataFrame:
    """1 if forward return > same-day cross-sectional median."""
    med = panel.group_by(date_col).agg(pl.col(label_col).median().alias("_med"))
    joined = panel.join(med, on=date_col, how="left")
    return joined.with_columns(
        pl.when(pl.col(label_col).is_not_null() & pl.col("_med").is_not_null())
        .then((pl.col(label_col) > pl.col("_med")).cast(pl.Float64))
        .otherwise(None)
        .alias("_y_bin")
    ).drop("_med")


def _select_ridge(
    x_tr: np.ndarray,
    y_tr: np.ndarray,
    x_va: np.ndarray,
    y_va: np.ndarray,
) -> tuple[Ridge, float, int]:
    best_model: Ridge | None = None
    best_alpha = RIDGE_ALPHAS[0]
    best_mse = float("inf")
    searches = 0
    for alpha in RIDGE_ALPHAS:
        searches += 1
        model = Ridge(alpha=alpha)
        model.fit(x_tr, y_tr)
        pred = model.predict(x_va)
        mse = float(mean_squared_error(y_va, pred))
        if mse < best_mse:
            best_mse = mse
            best_alpha = alpha
            best_model = model
    assert best_model is not None
    # Refit on train only (val used solely for selection).
    final = Ridge(alpha=best_alpha)
    final.fit(x_tr, y_tr)
    return final, best_alpha, searches


def _select_logistic(
    x_tr: np.ndarray,
    y_tr: np.ndarray,
    x_va: np.ndarray,
    y_va: np.ndarray,
) -> tuple[LogisticRegression, float, int]:
    best_model: LogisticRegression | None = None
    best_c = LOGISTIC_CS[0]
    best_acc = -1.0
    searches = 0
    # Need both classes in train.
    if len(np.unique(y_tr)) < 2:
        model = LogisticRegression(C=1.0, max_iter=500, random_state=0)
        # Degenerate: constant predictions later via predict_proba fallback.
        if len(y_tr):
            model.fit(x_tr, y_tr)
        return model, 1.0, 1

    for c in LOGISTIC_CS:
        searches += 1
        model = LogisticRegression(C=c, max_iter=500, random_state=0)
        model.fit(x_tr, y_tr)
        acc = float(model.score(x_va, y_va)) if len(y_va) else 0.0
        if acc > best_acc:
            best_acc = acc
            best_c = c
            best_model = model
    assert best_model is not None
    final = LogisticRegression(C=best_c, max_iter=500, random_state=0)
    final.fit(x_tr, y_tr)
    return final, best_c, searches


def _predict_fold(
    panel: pl.DataFrame,
    fold: WalkForwardFold,
    feature_cols: list[str],
    label_col: str,
    method: L3Method,
    date_col: str = "trade_date",
) -> tuple[pl.DataFrame, L3FoldDiag, int]:
    """Fit one fold; return (entity, date, score) for test rows + diagnostics."""
    ent = entity_col(panel)

    if method == "logistic":
        labeled = _cs_binary_label(panel, label_col, date_col)
        y_col = "_y_bin"
        work = labeled
    else:
        y_col = label_col
        work = panel

    tr = work.filter(
        (pl.col(date_col) >= fold.train_start) & (pl.col(date_col) <= fold.train_end)
    )
    va = work.filter(
        (pl.col(date_col) >= fold.val_start) & (pl.col(date_col) <= fold.val_end)
    )
    te = work.filter(
        (pl.col(date_col) >= fold.test_start) & (pl.col(date_col) <= fold.test_end)
    )

    x_tr, y_tr, ok_tr = _xy(tr, feature_cols, y_col, binary=False)
    x_va, y_va, ok_va = _xy(va, feature_cols, y_col, binary=False)
    x_te, _, ok_te = _xy(te, feature_cols, y_col, binary=False)

    x_tr, y_tr = x_tr[ok_tr], y_tr[ok_tr]
    x_va, y_va = x_va[ok_va], y_va[ok_va]

    searches = 0
    if method == "ridge":
        if len(y_tr) < 30 or len(y_va) < 10:
            raise ValueError(
                f"fold {fold.fold_id} ridge: insufficient samples "
                f"(train={len(y_tr)}, val={len(y_va)})"
            )
        model, param, searches = _select_ridge(x_tr, y_tr, x_va, y_va)
        scores = np.full(te.height, np.nan, dtype=np.float64)
        if ok_te.any():
            scores[ok_te] = model.predict(x_te[ok_te])
        coef = {c: float(w) for c, w in zip(feature_cols, model.coef_, strict=True)}
    else:
        if len(y_tr) < 30 or len(y_va) < 10:
            raise ValueError(
                f"fold {fold.fold_id} logistic: insufficient samples "
                f"(train={len(y_tr)}, val={len(y_va)})"
            )
        model, param, searches = _select_logistic(x_tr, y_tr, x_va, y_va)
        scores = np.full(te.height, np.nan, dtype=np.float64)
        if ok_te.any() and hasattr(model, "coef_"):
            proba = model.predict_proba(x_te[ok_te])
            # Column 1 = P(class=1) when both classes present.
            if proba.shape[1] == 2:
                scores[ok_te] = proba[:, 1]
            else:
                scores[ok_te] = proba[:, 0]
        coef = {}
        if hasattr(model, "coef_") and model.coef_ is not None:
            coef = {
                c: float(w) for c, w in zip(feature_cols, model.coef_.ravel(), strict=True)
            }

    out = te.select([ent, date_col]).with_columns(
        pl.Series("score", scores).cast(pl.Float64)
    )
    diag = L3FoldDiag(
        fold_id=fold.fold_id,
        method=method,
        best_param=float(param),
        n_train=int(len(y_tr)),
        n_val=int(len(y_va)),
        n_test=int(ok_te.sum()),
        test_start=fold.test_start,
        test_end=fold.test_end,
        coef=coef,
    )
    return out, diag, searches


def walk_forward_scores(
    panel: pl.DataFrame,
    feature_cols: list[str],
    *,
    method: L3Method,
    horizon: int = 5,
    wf: WalkForwardConfig | None = None,
    guard: HoldoutGuard | None = None,
    date_col: str = "trade_date",
    price_col: str = "close",
) -> tuple[pl.DataFrame, list[L3FoldDiag], int]:
    """Stitch OOS test scores across walk-forward folds."""
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
    diags: list[L3FoldDiag] = []
    total_searches = 0
    for fold in folds:
        part, diag, n_search = _predict_fold(
            labeled, fold, feature_cols, label_col, method, date_col=date_col
        )
        pieces.append(part)
        diags.append(diag)
        total_searches += n_search
        print(
            f"l3/{method}: fold={fold.fold_id} "
            f"train={fold.train_start}..{fold.train_end} "
            f"val={fold.val_start}..{fold.val_end} "
            f"test={fold.test_start}..{fold.test_end} "
            f"param={diag.best_param:g} n_test={diag.n_test}",
            flush=True,
        )

    scores = pl.concat(pieces)
    # Later folds overwrite overlapping test dates (should not overlap with defaults).
    scores = scores.unique(subset=[ent, date_col], keep="last")
    return scores, diags, total_searches


def run_l3_pipeline(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
    *,
    methods: tuple[L3Method, ...] = ("ridge", "logistic"),
    horizon: int = 5,
    n_quantiles: int = 5,
    decay_horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    min_names: int = 5,
    transform: bool = True,
    walk_forward: WalkForwardConfig | None = None,
    guard: HoldoutGuard | None = None,
) -> dict[str, FactorTestResult]:
    """Build L3 Ridge / Logistic OOS scores and evaluate like L1/L2 factors."""
    selected = list(codes) if codes is not None else list(CSI300_L1_ADMITTED_5Y)
    if not selected:
        raise ValueError("L3 requires at least one component factor")
    if not methods:
        raise ValueError("L3 requires at least one method")

    wf = walk_forward or WalkForwardConfig()
    panel = build_l2_panel(data, selected, transform=transform)
    for c in selected:
        if c not in panel.columns:
            raise KeyError(f"factor column missing after panel build: {c}")

    results: dict[str, FactorTestResult] = {}
    all_diags: list[L3FoldDiag] = []
    param_search_count = 0
    score_panel = panel

    method_cols: dict[L3Method, str] = {
        "ridge": COMBO_RIDGE,
        "logistic": COMBO_LOGISTIC,
    }

    for method in methods:
        out_col = method_cols[method]
        print(f"l3: walk-forward {method} on {len(selected)} factors", flush=True)
        scores, diags, n_search = walk_forward_scores(
            panel,
            selected,
            method=method,
            horizon=horizon,
            wf=wf,
            guard=guard,
        )
        param_search_count += n_search
        all_diags.extend(diags)
        ent = entity_col(panel)
        score_panel = score_panel.join(
            scores.rename({"score": out_col}),
            on=[ent, "trade_date"],
            how="left",
        )
        print(
            f"l3: evaluating {out_col} "
            f"(folds={len(diags)}, param_searches+={n_search})",
            flush=True,
        )
        results[out_col] = evaluate_factor(
            score_panel,
            factor_code=out_col,
            factor_col=out_col,
            horizon=horizon,
            n_quantiles=n_quantiles,
            decay_horizons=decay_horizons,
            other_factor_cols=selected,
            min_names=min_names,
        )
        note = (
            f"L3 {method} walk-forward OOS "
            f"(train={wf.train_months}m val={wf.val_months}m "
            f"test={wf.test_months}m step={wf.step_months}m "
            f"embargo={wf.embargo_days}d; not L1 admission)"
        )
        results[out_col].admission_notes = [note, *results[out_col].admission_notes]

    meta = L3RunMeta(
        methods=list(methods),
        components=selected,
        n_folds=len({d.fold_id for d in all_diags}),
        param_search_count=param_search_count,
        folds=all_diags,
        walk_forward={
            "train_months": wf.train_months,
            "val_months": wf.val_months,
            "test_months": wf.test_months,
            "step_months": wf.step_months,
            "embargo_days": wf.embargo_days,
            "holdout_start": (
                wf.holdout_start.isoformat() if wf.holdout_start else None
            ),
        },
    )
    data.meta["l3"] = {
        "methods": meta.methods,
        "components": meta.components,
        "n_folds": meta.n_folds,
        "param_search_count": meta.param_search_count,
        "walk_forward": meta.walk_forward,
        "folds": [
            {
                "fold_id": d.fold_id,
                "method": d.method,
                "best_param": d.best_param,
                "n_train": d.n_train,
                "n_val": d.n_val,
                "n_test": d.n_test,
                "test_start": d.test_start.isoformat(),
                "test_end": d.test_end.isoformat(),
                "coef": d.coef,
            }
            for d in all_diags
        ],
    }
    return results
