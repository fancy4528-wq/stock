"""Quantile (layer) tests and long-short metrics."""

from __future__ import annotations

from math import sqrt

import numpy as np
import polars as pl
from scipy import stats  # type: ignore[import-untyped]

from quantagent.quant.evaluation.ic import EvaluationError
from quantagent.quant.evaluation.types import QuantileSummary


def assign_quantiles(
    panel: pl.DataFrame,
    *,
    factor_col: str,
    date_col: str = "trade_date",
    n_quantiles: int = 5,
) -> pl.DataFrame:
    """Add ``q`` in ``1..n_quantiles`` (1=lowest factor, n=highest) per date."""
    if n_quantiles < 2:
        raise EvaluationError(f"n_quantiles must be >= 2, got {n_quantiles}")
    if factor_col not in panel.columns or date_col not in panel.columns:
        raise EvaluationError("panel missing factor or date column")

    return (
        panel.with_columns(pl.col(factor_col).rank(method="average").over(date_col).alias("_rank"))
        .with_columns(
            pl.col(factor_col).count().over(date_col).alias("_n"),
        )
        .with_columns(
            pl.when(pl.col(factor_col).is_null() | (pl.col("_n") < 2))
            .then(None)
            .otherwise(
                ((pl.col("_rank") - 1.0) / (pl.col("_n") - 1.0).clip(lower_bound=1) * n_quantiles)
                .floor()
                .cast(pl.Int64)
                .clip(0, n_quantiles - 1)
                + 1
            )
            .alias("q")
        )
        .drop(["_rank", "_n"])
    )


def monotonicity_score(quantile_means: list[float]) -> float:
    """Spearman corr of quantile index vs mean return; in [-1, 1]."""
    if len(quantile_means) < 2:
        return 0.0
    xs = np.arange(1, len(quantile_means) + 1, dtype=float)
    ys = np.asarray(quantile_means, dtype=float)
    if np.nanstd(ys) < 1e-15:
        return 0.0
    corr, _ = stats.spearmanr(xs, ys)
    if corr is None or np.isnan(corr):
        return 0.0
    return float(corr)


def quantile_analysis(
    panel: pl.DataFrame,
    *,
    factor_col: str,
    return_col: str,
    date_col: str = "trade_date",
    n_quantiles: int = 5,
    min_names: int = 5,
) -> QuantileSummary:
    """Average forward return by factor quantile + long-short Sharpe."""
    for c in (factor_col, return_col, date_col):
        if c not in panel.columns:
            raise EvaluationError(f"panel missing column: {c}")

    clean = panel.select([date_col, factor_col, return_col]).drop_nulls()
    if clean.is_empty():
        return QuantileSummary(
            n_quantiles=n_quantiles,
            quantile_returns=[0.0] * n_quantiles,
            monotonicity=0.0,
            long_short_return=0.0,
            long_short_sharpe=0.0,
        )

    counts = clean.group_by(date_col).len()
    ok_dates = set(counts.filter(pl.col("len") >= min_names)[date_col].to_list())
    clean = clean.filter(pl.col(date_col).is_in(list(ok_dates)))
    if clean.is_empty():
        return QuantileSummary(
            n_quantiles=n_quantiles,
            quantile_returns=[0.0] * n_quantiles,
            monotonicity=0.0,
            long_short_return=0.0,
            long_short_sharpe=0.0,
        )

    ranked = assign_quantiles(
        clean, factor_col=factor_col, date_col=date_col, n_quantiles=n_quantiles
    )

    daily_q = (
        ranked.group_by([date_col, "q"], maintain_order=True)
        .agg(pl.col(return_col).mean().alias("qret"))
        .drop_nulls()
    )

    means: list[float] = []
    for q in range(1, n_quantiles + 1):
        sub = daily_q.filter(pl.col("q") == q)["qret"]
        means.append(float(sub.mean()) if sub.len() else 0.0)  # type: ignore[arg-type]

    wide = daily_q.pivot(on="q", index=date_col, values="qret", aggregate_function="first")
    top_col = str(n_quantiles)
    bot_col = "1"
    if top_col in wide.columns and bot_col in wide.columns:
        ls = (wide[top_col] - wide[bot_col]).drop_nulls()
        ls_vals = [float(v) for v in ls.to_list()]
    else:
        ls_vals = []

    if ls_vals:
        arr = np.asarray(ls_vals, dtype=float)
        ls_mean = float(arr.mean())
        ls_std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        sharpe = (ls_mean / ls_std) * sqrt(len(arr)) if ls_std > 1e-15 else 0.0
    else:
        ls_mean = 0.0
        sharpe = 0.0

    return QuantileSummary(
        n_quantiles=n_quantiles,
        quantile_returns=means,
        monotonicity=monotonicity_score(means),
        long_short_return=ls_mean,
        long_short_sharpe=float(sharpe),
    )
