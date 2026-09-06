"""Orchestrate single- / multi-factor evaluation into FactorTestResult."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

import numpy as np
import polars as pl

from quantagent.quant.evaluation.decay import ic_decay
from quantagent.quant.evaluation.ic import (
    EvaluationError,
    daily_ic_series,
    ic_by_regime,
    ic_by_year,
    summarize_ic,
)
from quantagent.quant.evaluation.quantile import quantile_analysis
from quantagent.quant.evaluation.types import FactorTestResult
from quantagent.quant.features.base import entity_col
from quantagent.quant.labels.targets import attach_forward_returns, forward_return_col

# docs/07-quant-engine.md §3.2
IC_MEAN_ABS_MIN: Final[float] = 0.02
IC_T_ABS_MIN: Final[float] = 2.0
IC_POS_RATIO_LO: Final[float] = 0.45
IC_POS_RATIO_HI: Final[float] = 0.55
ICIR_ABS_MIN: Final[float] = 0.3
CORR_MAX: Final[float] = 0.7
YEAR_SAME_SIGN_MIN: Final[float] = 0.60

ADMISSION: Final[dict[str, float]] = {
    "ic_mean_abs_min": IC_MEAN_ABS_MIN,
    "ic_t_abs_min": IC_T_ABS_MIN,
    "icir_abs_min": ICIR_ABS_MIN,
    "corr_max": CORR_MAX,
    "year_same_sign_min": YEAR_SAME_SIGN_MIN,
}


def passes_admission(result: FactorTestResult) -> tuple[bool, list[str]]:
    """Check Gate-style L1 thresholds; return (ok, notes)."""
    notes: list[str] = []
    ok = True

    if abs(result.ic_mean) < IC_MEAN_ABS_MIN:
        ok = False
        notes.append(f"|ic_mean|={abs(result.ic_mean):.4f} < {IC_MEAN_ABS_MIN}")
    else:
        notes.append(f"|ic_mean|={abs(result.ic_mean):.4f} ok")

    if abs(result.ic_t_stat) < IC_T_ABS_MIN:
        ok = False
        notes.append(f"|ic_t|={abs(result.ic_t_stat):.3f} < {IC_T_ABS_MIN}")
    else:
        notes.append(f"|ic_t|={abs(result.ic_t_stat):.3f} ok")

    pr = result.ic_positive_ratio
    if IC_POS_RATIO_LO < pr < IC_POS_RATIO_HI:
        ok = False
        notes.append(
            f"ic_positive_ratio={pr:.3f} inside "
            f"({IC_POS_RATIO_LO},{IC_POS_RATIO_HI}) — weak direction"
        )
    else:
        notes.append(f"ic_positive_ratio={pr:.3f} ok")

    if abs(result.icir) < ICIR_ABS_MIN:
        ok = False
        notes.append(f"|icir|={abs(result.icir):.3f} < {ICIR_ABS_MIN}")
    else:
        notes.append(f"|icir|={abs(result.icir):.3f} ok")

    if result.ic_by_year:
        signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in result.ic_by_year.values()]
        nonzero = [s for s in signs if s != 0]
        if nonzero:
            majority = max(nonzero.count(1), nonzero.count(-1)) / len(nonzero)
            if majority < YEAR_SAME_SIGN_MIN:
                ok = False
                notes.append(f"year same-sign={majority:.0%} < {YEAR_SAME_SIGN_MIN:.0%}")
            else:
                notes.append(f"year same-sign={majority:.0%} ok")

    for other, corr in result.correlations.items():
        if abs(corr) >= CORR_MAX:
            ok = False
            notes.append(f"corr({other})={corr:.3f} >= {CORR_MAX}")

    return ok, notes


def _factor_autocorr(
    panel: pl.DataFrame,
    *,
    factor_col: str,
    date_col: str = "trade_date",
) -> float:
    """Mean cross-sectional Spearman between factor_t and factor_{t-1}."""
    ent = entity_col(panel)
    shifted = panel.select([ent, date_col, factor_col]).sort([ent, date_col])
    shifted = shifted.with_columns(pl.col(factor_col).shift(1).over(ent).alias("_lag"))
    ics = daily_ic_series(
        shifted,
        factor_col=factor_col,
        return_col="_lag",
        date_col=date_col,
        min_names=3,
    )
    if ics.is_empty():
        return 0.0
    mean = ics["ic"].mean()
    if mean is None:
        return 0.0
    return float(mean)  # type: ignore[arg-type]


def _pairwise_factor_corr(
    panel: pl.DataFrame,
    *,
    factor_col: str,
    other_cols: list[str],
    date_col: str = "trade_date",
) -> dict[str, float]:
    out: dict[str, float] = {}
    for other in other_cols:
        if other == factor_col or other not in panel.columns:
            continue
        ics = daily_ic_series(
            panel,
            factor_col=factor_col,
            return_col=other,
            date_col=date_col,
            min_names=3,
        )
        if ics.is_empty():
            continue
        mean = ics["ic"].mean()
        if mean is None:
            continue
        out[other] = float(mean)  # type: ignore[arg-type]
    return out


def evaluate_factor(
    panel: pl.DataFrame,
    *,
    factor_code: str,
    factor_col: str | None = None,
    horizon: int = 5,
    n_quantiles: int = 5,
    decay_horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    price_col: str = "close",
    date_col: str = "trade_date",
    other_factor_cols: list[str] | None = None,
    min_names: int = 5,
) -> FactorTestResult:
    """Evaluate one factor column on a panel that includes prices + factor.

    Panel must include entity (``security_id`` or ``symbol``), ``trade_date``,
    ``close`` (or ``price_col``), and the factor column. Extra columns are kept.
    """
    factor_col = factor_col or factor_code
    for col, label in (
        (factor_col, "factor"),
        (date_col, "date"),
        (price_col, "price"),
    ):
        if col not in panel.columns:
            raise EvaluationError(f"{label} column not in panel: {col}")

    horizons = sorted(set([horizon, *decay_horizons]))
    labeled = attach_forward_returns(panel, horizons=horizons, price_col=price_col)
    ret_col = forward_return_col(horizon)
    ent = entity_col(labeled)

    eval_panel = labeled.select([ent, date_col, factor_col, ret_col])

    ics = daily_ic_series(
        eval_panel,
        factor_col=factor_col,
        return_col=ret_col,
        date_col=date_col,
        min_names=min_names,
    )
    ic_sum = summarize_ic(ics["ic"] if not ics.is_empty() else pl.Series([], dtype=pl.Float64))

    q_sum = quantile_analysis(
        eval_panel,
        factor_col=factor_col,
        return_col=ret_col,
        date_col=date_col,
        n_quantiles=n_quantiles,
        min_names=min_names,
    )

    dh, dm = ic_decay(
        labeled,
        factor_col=factor_col,
        price_col=price_col,
        horizons=decay_horizons,
        date_col=date_col,
        min_names=min_names,
    )

    by_year = ic_by_year(ics, date_col=date_col)
    by_regime = ic_by_regime(eval_panel, ics, return_col=ret_col, date_col=date_col)
    ac = _factor_autocorr(eval_panel, factor_col=factor_col, date_col=date_col)
    turnover_est = float(max(0.0, 1.0 - abs(ac)))

    skip = {
        ent,
        date_col,
        price_col,
        "open",
        "high",
        "low",
        "volume",
        "amount",
        "turnover_rate",
        factor_col,
    }
    others = other_factor_cols or [
        c for c in panel.columns if c not in skip and not str(c).startswith("fwd_ret_")
    ]
    corrs = _pairwise_factor_corr(
        labeled,
        factor_col=factor_col,
        other_cols=others,
        date_col=date_col,
    )

    dates = panel[date_col].drop_nulls().to_list()
    if not dates:
        raise EvaluationError("panel has no trade_date values")
    start_d = min(dates)
    end_d = max(dates)
    assert isinstance(start_d, date) and isinstance(end_d, date)

    result = FactorTestResult(
        factor_code=factor_code,
        period=(start_d, end_d),
        horizon_days=horizon,
        n_quantiles=n_quantiles,
        ic_mean=ic_sum.ic_mean,
        ic_std=ic_sum.ic_std,
        icir=ic_sum.icir,
        ic_t_stat=ic_sum.ic_t_stat,
        ic_p_value=ic_sum.ic_p_value,
        ic_positive_ratio=ic_sum.ic_positive_ratio,
        n_ic_periods=ic_sum.n_periods,
        quantile_returns=q_sum.quantile_returns,
        monotonicity=q_sum.monotonicity,
        long_short_return=q_sum.long_short_return,
        long_short_sharpe=q_sum.long_short_sharpe,
        ic_decay=dm,
        ic_decay_horizons=dh,
        ic_by_year=by_year,
        ic_by_regime=by_regime,
        autocorrelation=ac,
        turnover_estimate=turnover_est,
        correlations=corrs,
    )
    passed, notes = passes_admission(result)
    result.admission_pass = passed
    result.admission_notes = notes
    return result


def evaluate_factors(
    panel: pl.DataFrame,
    factor_cols: list[str],
    *,
    horizon: int = 5,
    n_quantiles: int = 5,
    decay_horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    price_col: str = "close",
    date_col: str = "trade_date",
    min_names: int = 5,
) -> dict[str, FactorTestResult]:
    """Evaluate multiple factor columns; each sees the others for correlations."""
    results: dict[str, FactorTestResult] = {}
    for code in factor_cols:
        results[code] = evaluate_factor(
            panel,
            factor_code=code,
            factor_col=code,
            horizon=horizon,
            n_quantiles=n_quantiles,
            decay_horizons=decay_horizons,
            price_col=price_col,
            date_col=date_col,
            other_factor_cols=[c for c in factor_cols if c != code],
            min_names=min_names,
        )
    return results


def synthetic_eval_panel(
    *,
    n_dates: int = 60,
    n_names: int = 40,
    seed: int = 42,
    signal_strength: float = 0.8,
    start: date = date(2024, 1, 2),
) -> pl.DataFrame:
    """Build a panel where ``good_factor`` predicts 5d forward returns."""
    rng = np.random.default_rng(seed)

    dates: list[date] = []
    d = start
    while len(dates) < n_dates:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)

    rows: list[dict[str, object]] = []
    for td in dates:
        for sid in range(1, n_names + 1):
            rows.append(
                {
                    "security_id": sid,
                    "trade_date": td,
                    "good_factor": float(rng.normal()),
                    "noise_factor": float(rng.normal()),
                }
            )
    base = pl.DataFrame(rows).sort(["security_id", "trade_date"])
    eps = rng.normal(0, 0.02, size=base.height)
    fwd = signal_strength * 0.02 * base["good_factor"].to_numpy() + eps
    base = base.with_columns(pl.Series("_fwd5", fwd))

    closes: list[float] = []
    for sid in range(1, n_names + 1):
        sub = base.filter(pl.col("security_id") == sid)
        n = sub.height
        c = np.ones(n, dtype=float) * 100.0
        f = sub["_fwd5"].to_numpy()
        for i in range(n - 6, -1, -1):
            denom = 1.0 + float(f[i])
            if abs(denom) < 1e-9:
                denom = 1e-9
            c[i] = c[i + 5] / denom
        closes.extend(c.tolist())

    return (
        base.with_columns(pl.Series("close", closes))
        .drop("_fwd5")
        .select(["security_id", "trade_date", "close", "good_factor", "noise_factor"])
    )
