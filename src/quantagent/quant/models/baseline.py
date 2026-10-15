"""L0–L2 baselines. L2: sign-aligned equal-weight / IC-weighted factor blend."""

from __future__ import annotations

from typing import Final, Literal

import polars as pl

from quantagent.quant.evaluation.ic import daily_ic_series, summarize_ic
from quantagent.quant.evaluation.runner import evaluate_factor, evaluate_factors
from quantagent.quant.evaluation.types import FactorTestResult
from quantagent.quant.features.base import FactorInput, entity_col
from quantagent.quant.features.compute import build_factor_panel
from quantagent.quant.features.transform import (
    DEFAULT_TRANSFORM,
    TransformConfig,
    attach_cs_covariates,
    transform_cross_section,
    transform_meta,
)
from quantagent.quant.labels.targets import attach_forward_returns, forward_return_col

# CSI300 5y L1 greedy admission (docs/factor-reports-csi300-5y, 2026-10-14).
CSI300_L1_ADMITTED_5Y: Final[tuple[str, ...]] = (
    "max_ret_20d",
    "skew_60d",
    "turnover_20d",
    "vol_60d",
    "ep_ttm",
    "vol_price_corr_20d",
    "bp",
)

L2Method = Literal["equal", "ic"]

COMBO_EQUAL: Final[str] = "l2_equal"
COMBO_IC: Final[str] = "l2_ic"


def ic_weight_dict(ic_means: dict[str, float]) -> dict[str, float]:
    """Weights proportional to IC mean with ``Σ|w| = 1`` (sign preserved)."""
    if not ic_means:
        raise ValueError("ic_means is empty")
    total = sum(abs(v) for v in ic_means.values())
    if total <= 0:
        n = len(ic_means)
        return {k: 1.0 / n for k in ic_means}
    return {k: float(v) / total for k, v in ic_means.items()}


def sign_align_panel(
    panel: pl.DataFrame,
    codes: list[str],
    ic_means: dict[str, float],
    *,
    suffix: str = "_aligned",
) -> pl.DataFrame:
    """Map rank factors so higher = expected higher return.

    For ``rank_pct`` in ``[0, 1]``: keep ``f`` when IC > 0, else ``1 - f``.
    Zero / missing IC leaves the column unchanged.
    """
    exprs: list[pl.Expr] = []
    for code in codes:
        if code not in panel.columns:
            raise KeyError(f"factor column missing: {code}")
        ic = float(ic_means.get(code, 0.0))
        col = pl.col(code).cast(pl.Float64, strict=False)
        if ic < 0:
            aligned = (1.0 - col).alias(f"{code}{suffix}")
        else:
            aligned = col.alias(f"{code}{suffix}")
        exprs.append(aligned)
    return panel.with_columns(exprs)


def combine_equal_weight(
    panel: pl.DataFrame,
    codes: list[str],
    ic_means: dict[str, float],
    *,
    out_col: str = COMBO_EQUAL,
) -> pl.DataFrame:
    """Sign-align then equal-weight mean of available component ranks."""
    aligned = sign_align_panel(panel, codes, ic_means)
    cols = [f"{c}_aligned" for c in codes]
    # Mean over non-null components so sparse industry rows don't zero the score.
    score = pl.mean_horizontal([pl.col(c) for c in cols]).alias(out_col)
    return aligned.with_columns(score)


def combine_ic_weight(
    panel: pl.DataFrame,
    codes: list[str],
    ic_means: dict[str, float],
    *,
    out_col: str = COMBO_IC,
) -> pl.DataFrame:
    """Sign-align then weight by ``|IC|`` (normalized to sum 1)."""
    aligned = sign_align_panel(panel, codes, ic_means)
    abs_w = {c: abs(float(ic_means.get(c, 0.0))) for c in codes}
    total = sum(abs_w.values())
    if total <= 0:
        weights = {c: 1.0 / len(codes) for c in codes}
    else:
        weights = {c: abs_w[c] / total for c in codes}

    # Renormalize per row over non-null components.
    parts: list[pl.Expr] = []
    w_parts: list[pl.Expr] = []
    for c in codes:
        a = pl.col(f"{c}_aligned")
        w = float(weights[c])
        parts.append(pl.when(a.is_not_null()).then(a * w).otherwise(None))
        w_parts.append(pl.when(a.is_not_null()).then(pl.lit(w)).otherwise(None))
    numer = pl.sum_horizontal(parts)
    denom = pl.sum_horizontal(w_parts)
    score = (
        pl.when(denom.is_not_null() & (denom > 0))
        .then(numer / denom)
        .otherwise(None)
        .alias(out_col)
    )
    return aligned.with_columns(score)


def estimate_ic_means(
    panel: pl.DataFrame,
    codes: list[str],
    *,
    horizon: int = 5,
    date_col: str = "trade_date",
    price_col: str = "close",
    min_names: int = 5,
) -> dict[str, float]:
    """Full-window mean Spearman IC per factor (for blend weights / signs)."""
    labeled = attach_forward_returns(panel, horizons=[horizon], price_col=price_col)
    ret_col = forward_return_col(horizon)
    out: dict[str, float] = {}
    for code in codes:
        ics = daily_ic_series(
            labeled.select([entity_col(labeled), date_col, code, ret_col]),
            factor_col=code,
            return_col=ret_col,
            date_col=date_col,
            min_names=min_names,
        )
        summary = summarize_ic(
            ics["ic"] if not ics.is_empty() else pl.Series([], dtype=pl.Float64)
        )
        out[code] = float(summary.ic_mean)
    return out


def build_l2_panel(
    data: FactorInput,
    codes: list[str],
    *,
    transform: TransformConfig | bool = DEFAULT_TRANSFORM,
) -> pl.DataFrame:
    """Compute + optional CS transform for the component factors."""
    cfg = (
        transform
        if isinstance(transform, TransformConfig)
        else TransformConfig(enabled=bool(transform))
    )
    panel = build_factor_panel(data, codes=codes)
    if cfg.enabled:
        panel = attach_cs_covariates(panel, data)
        meta = transform_meta(panel, cfg)
        data.meta.update(meta)
        print(
            "l2: transform "
            f"mad_n={cfg.mad_n} industry={meta['neutralize_industry']} "
            f"mktcap={meta['neutralize_mktcap']} rank={meta['rank_pct']}",
            flush=True,
        )
        panel = transform_cross_section(panel, codes, config=cfg)
    return panel


def run_l2_pipeline(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
    *,
    methods: tuple[L2Method, ...] = ("equal", "ic"),
    horizon: int = 5,
    n_quantiles: int = 5,
    decay_horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    min_names: int = 5,
    transform: TransformConfig | bool = DEFAULT_TRANSFORM,
    evaluate_components: bool = True,
) -> dict[str, FactorTestResult]:
    """Build L2 equal / IC-weighted scores and evaluate them like L1 factors.

    Component directions are taken from full-window mean IC on the same panel
    (in-sample baseline; walk-forward weights belong with L3+).
    """
    selected = list(codes) if codes is not None else list(CSI300_L1_ADMITTED_5Y)
    if not selected:
        raise ValueError("L2 requires at least one component factor")

    panel = build_l2_panel(data, selected, transform=transform)
    ic_means = estimate_ic_means(
        panel, selected, horizon=horizon, min_names=min_names
    )
    print(
        "l2: component IC means → "
        + ", ".join(f"{k}={v:+.4f}" for k, v in ic_means.items()),
        flush=True,
    )

    results: dict[str, FactorTestResult] = {}
    if evaluate_components:
        print(f"l2: evaluating {len(selected)} components", flush=True)
        results.update(
            evaluate_factors(
                panel,
                selected,
                horizon=horizon,
                n_quantiles=n_quantiles,
                decay_horizons=decay_horizons,
                min_names=min_names,
            )
        )

    combo_panel = panel
    combo_cols: list[str] = []
    flipped = [c for c in selected if ic_means.get(c, 0.0) < 0]
    if "equal" in methods:
        combo_panel = combine_equal_weight(combo_panel, selected, ic_means)
        combo_cols.append(COMBO_EQUAL)
        print(
            f"l2: equal-weight = mean(sign-aligned ranks); flipped={flipped}",
            flush=True,
        )
    if "ic" in methods:
        # Align/weight from original ranks; drop transient *_aligned from equal step.
        scored = combine_ic_weight(panel, selected, ic_means)
        ent = entity_col(panel)
        keep = [c for c in combo_panel.columns if not c.endswith("_aligned")]
        combo_panel = combo_panel.select(keep).join(
            scored.select([ent, "trade_date", COMBO_IC]),
            on=[ent, "trade_date"],
            how="left",
        )
        combo_cols.append(COMBO_IC)
        abs_w = {c: abs(ic_means[c]) for c in selected}
        tw = sum(abs_w.values()) or 1.0
        print(
            "l2: IC-weight ∝ |IC| → "
            + ", ".join(f"{c}={abs_w[c] / tw:.3f}" for c in selected),
            flush=True,
        )
    else:
        combo_panel = combo_panel.drop(
            [c for c in combo_panel.columns if c.endswith("_aligned")]
        )

    horizons = sorted(set([horizon, *decay_horizons]))
    labeled = attach_forward_returns(combo_panel, horizons=horizons, price_col="close")
    for col in combo_cols:
        print(f"l2: evaluating combo {col}", flush=True)
        results[col] = evaluate_factor(
            combo_panel,
            factor_code=col,
            factor_col=col,
            horizon=horizon,
            n_quantiles=n_quantiles,
            decay_horizons=decay_horizons,
            other_factor_cols=selected,
            min_names=min_names,
            labeled_panel=labeled,
        )
        note = (
            "L2 combo baseline (not subject to L1 pairwise-corr admission vs inventory)"
        )
        results[col].admission_notes = [note, *results[col].admission_notes]

    data.meta["l2_ic_means"] = ic_means
    data.meta["l2_methods"] = list(methods)
    data.meta["l2_components"] = selected
    return results
