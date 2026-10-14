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
from quantagent.quant.features.base import FactorInput, entity_col
from quantagent.quant.features.compute import build_factor_panel
from quantagent.quant.features.registry import (
    ALL_FACTOR_CODES,
    L1_SYNTHETIC_CODES,
    MVP_FACTOR_CODES,
)
from quantagent.quant.features.transform import (
    DEFAULT_TRANSFORM,
    TransformConfig,
    attach_cs_covariates,
    transform_cross_section,
    transform_meta,
)
from quantagent.quant.labels.targets import (
    attach_forward_returns,
    forward_return_col,
    tradeability_label_stats,
)

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


def passes_admission(
    result: FactorTestResult,
    *,
    admitted_codes: frozenset[str] | set[str] | None = None,
) -> tuple[bool, list[str]]:
    """Check Gate-style L1 thresholds; return (ok, notes).

    Pairwise corr is only enforced against ``admitted_codes`` (docs/07 §3.2
    「与已有因子相关性」). Pass an empty set for metrics-only; omit / ``None``
    also means metrics-only (single-factor eval has no admitted inventory yet).
    """
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

    if admitted_codes is not None:
        for other, corr in result.correlations.items():
            if other not in admitted_codes:
                continue
            if abs(corr) >= CORR_MAX:
                ok = False
                notes.append(f"corr({other})={corr:.3f} >= {CORR_MAX}")

    return ok, notes


def apply_greedy_admission(
    results: dict[str, FactorTestResult],
) -> list[str]:
    """Admit by |ICIR| desc among metric-passers; corr only vs already admitted.

    Mutates ``admission_pass`` / ``admission_notes`` on each result. Returns the
    ordered list of admitted factor codes.
    """
    metrics_ok: list[FactorTestResult] = []
    for result in results.values():
        ok, notes = passes_admission(result, admitted_codes=frozenset())
        if ok:
            metrics_ok.append(result)
        else:
            result.admission_pass = False
            result.admission_notes = notes

    metrics_ok.sort(key=lambda r: abs(r.icir), reverse=True)
    admitted: list[str] = []
    admitted_set: set[str] = set()
    for result in metrics_ok:
        ok, notes = passes_admission(result, admitted_codes=admitted_set)
        result.admission_pass = ok
        result.admission_notes = notes
        if ok:
            admitted.append(result.factor_code)
            admitted_set.add(result.factor_code)
    return admitted


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


def _mean_factor_corr_matrix(
    panel: pl.DataFrame,
    factor_cols: list[str],
    *,
    date_col: str = "trade_date",
    min_names: int = 3,
) -> dict[str, dict[str, float]]:
    """Mean daily cross-sectional Spearman between every factor pair (upper triangle)."""
    matrix: dict[str, dict[str, float]] = {c: {} for c in factor_cols}
    for i, a in enumerate(factor_cols):
        for b in factor_cols[i + 1 :]:
            if a not in panel.columns or b not in panel.columns:
                continue
            ics = daily_ic_series(
                panel,
                factor_col=a,
                return_col=b,
                date_col=date_col,
                min_names=min_names,
            )
            if ics.is_empty():
                continue
            mean = ics["ic"].mean()
            if mean is None:
                continue
            val = float(mean)  # type: ignore[arg-type]
            matrix[a][b] = val
            matrix[b][a] = val
    return matrix


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
    labeled_panel: pl.DataFrame | None = None,
    precomputed_correlations: dict[str, float] | None = None,
) -> FactorTestResult:
    """Evaluate one factor column on a panel that includes prices + factor.

    Panel must include entity (``security_id`` or ``symbol``), ``trade_date``,
    ``close`` (or ``price_col``), and the factor column. Extra columns are kept.

    When evaluating many factors, pass a shared ``labeled_panel`` (with forward
    returns already attached) and ``precomputed_correlations`` from
    :func:`evaluate_factors` to avoid O(n²) recomputation.
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
    if labeled_panel is not None:
        labeled = labeled_panel
        missing_h = [h for h in horizons if forward_return_col(h) not in labeled.columns]
        if missing_h:
            labeled = attach_forward_returns(labeled, horizons=missing_h, price_col=price_col)
    else:
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

    if precomputed_correlations is not None:
        corrs = dict(precomputed_correlations)
    else:
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
            "industry_code",
            "industry_name",
            "log_mktcap",
            "market_cap",
            "circ_market_cap",
            "pe_ttm",
            "pb",
            "ps_ttm",
            "prev_close",
            "is_limit_up",
            "is_limit_down",
            "is_suspended",
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
    horizons = sorted(set([horizon, *decay_horizons]))
    stats = tradeability_label_stats(panel)
    if stats.get("flags_present"):
        n_bad = stats["n_untradeable_entry"]
        n_all = stats["n_rows"]
        pct = 100.0 * n_bad / n_all if n_all else 0.0
        print(
            f"evaluate: label mask T+1 limit-up/suspended → "
            f"{n_bad}/{n_all} rows ({pct:.2f}%)",
            flush=True,
        )
    labeled = attach_forward_returns(panel, horizons=horizons, price_col=price_col)
    corr_matrix = _mean_factor_corr_matrix(
        labeled,
        factor_cols,
        date_col=date_col,
        min_names=3,
    )
    results: dict[str, FactorTestResult] = {}
    n = len(factor_cols)
    for i, code in enumerate(factor_cols, start=1):
        print(f"evaluate: [{i}/{n}] {code}", flush=True)
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
            labeled_panel=labeled,
            precomputed_correlations=corr_matrix.get(code, {}),
        )
    admitted = apply_greedy_admission(results)
    print(
        f"evaluate: greedy admission vs admitted-set → {len(admitted)} pass "
        f"({', '.join(admitted) if admitted else 'none'})",
        flush=True,
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


def _trading_dates(*, n_dates: int, start: date) -> list[date]:
    dates: list[date] = []
    d = start
    while len(dates) < n_dates:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    return dates


def synthetic_price_panel(
    *,
    n_dates: int = 280,
    n_names: int = 40,
    seed: int = 42,
    signal_strength: float = 0.2,
    start: date = date(2023, 1, 3),
) -> pl.DataFrame:
    """Synthetic OHLCV + simple valuation multiples (no factor columns)."""
    rng = np.random.default_rng(seed)
    dates = _trading_dates(n_dates=n_dates, start=start)
    rows: list[dict[str, object]] = []

    for sid in range(1, n_names + 1):
        closes = [100.0 + sid * 0.05]
        for i in range(1, len(dates)):
            if i >= 21 and np.isfinite(closes[i - 1]) and np.isfinite(closes[i - 21]):
                mom = closes[i - 1] / closes[i - 21] - 1.0
                ret = signal_strength * mom * 0.5 + float(rng.normal(0, 0.015))
            else:
                ret = float(rng.normal(0, 0.02))
            # Keep paths finite over long L1 panels (mom feedback otherwise → inf).
            ret = float(np.clip(ret, -0.12, 0.12))
            nxt = closes[-1] * (1.0 + ret)
            if not np.isfinite(nxt) or nxt <= 1e-6:
                nxt = closes[-1] * (1.0 + float(rng.normal(0, 0.01)))
            closes.append(float(np.clip(nxt, 1e-3, 1e6)))

        for i, td in enumerate(dates):
            close = closes[i]
            prev = closes[i - 1] if i > 0 else close
            open_px = prev * (1.0 + float(rng.normal(0, 0.002)))
            high = max(open_px, close) * (1.0 + abs(float(rng.normal(0, 0.003))))
            low = min(open_px, close) * (1.0 - abs(float(rng.normal(0, 0.003))))
            turnover = 0.01 + float(rng.uniform(0, 0.03))
            volume = 500_000.0 + float(rng.uniform(0, 1_500_000.0))
            amount = close * volume * turnover / 0.02
            rows.append(
                {
                    "security_id": sid,
                    "trade_date": td,
                    "open": open_px,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "turnover_rate": turnover,
                    "industry_code": f"I{sid % 4}",
                    "pe_ttm": 10.0 + sid * 0.1 + float(rng.uniform(-2, 2)),
                    "pb": 1.5 + sid * 0.02 + float(rng.uniform(-0.3, 0.3)),
                    "ps_ttm": 3.0 + sid * 0.05 + float(rng.uniform(-0.5, 0.5)),
                }
            )

    return pl.DataFrame(rows).sort(["security_id", "trade_date"])


def synthetic_l1_eval_panel(
    *,
    n_dates: int = 280,
    n_names: int = 40,
    seed: int = 42,
    signal_strength: float = 0.2,
    start: date = date(2023, 1, 3),
    codes: list[str] | tuple[str, ...] | None = None,
) -> pl.DataFrame:
    """Build OHLCV panel and compute registered factors for L1 evaluation."""
    prices = synthetic_price_panel(
        n_dates=n_dates,
        n_names=n_names,
        seed=seed,
        signal_strength=signal_strength,
        start=start,
    )
    selected = list(codes) if codes is not None else list(L1_SYNTHETIC_CODES)
    as_of = prices["trade_date"].max()
    assert isinstance(as_of, date)
    panel = build_factor_panel(FactorInput(prices=prices, as_of=as_of), codes=selected)
    keep = ["security_id", "trade_date", "close", *selected]
    return panel.select([c for c in keep if c in panel.columns])


def synthetic_mvp_eval_panel(
    *,
    n_dates: int = 120,
    n_names: int = 40,
    seed: int = 42,
    signal_strength: float = 0.4,
    start: date = date(2024, 1, 2),
) -> pl.DataFrame:
    """Backward-compatible MVP-only synthetic panel (P1 W6 / single-factor backtest)."""
    return synthetic_l1_eval_panel(
        n_dates=n_dates,
        n_names=n_names,
        seed=seed,
        signal_strength=signal_strength,
        start=start,
        codes=MVP_FACTOR_CODES,
    )


def run_l1_pipeline(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
    *,
    horizon: int = 5,
    n_quantiles: int = 5,
    decay_horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    min_names: int = 5,
    transform: TransformConfig | bool = DEFAULT_TRANSFORM,
) -> dict[str, FactorTestResult]:
    """Compute factors, optionally transform cross-sections, then L1 admit.

    ``data.prices`` must include ``close`` (and any columns required by the
    selected factors). Returns one :class:`FactorTestResult` per code.

    When ``transform`` is enabled (default), each factor is MAD-winsorized,
    neutralized to industry / log-mktcap when available, then ``rank_pct``.
    """
    selected = list(codes) if codes is not None else list(ALL_FACTOR_CODES)
    cfg = (
        transform
        if isinstance(transform, TransformConfig)
        else TransformConfig(enabled=bool(transform))
    )
    panel = build_factor_panel(data, codes=selected)
    if cfg.enabled:
        panel = attach_cs_covariates(panel, data)
        meta = transform_meta(panel, cfg)
        data.meta.update(meta)
        print(
            "evaluate: transform "
            f"mad_n={cfg.mad_n} industry={meta['neutralize_industry']} "
            f"mktcap={meta['neutralize_mktcap']} rank={meta['rank_pct']}",
            flush=True,
        )
        panel = transform_cross_section(panel, selected, config=cfg)
    return evaluate_factors(
        panel,
        selected,
        horizon=horizon,
        n_quantiles=n_quantiles,
        decay_horizons=decay_horizons,
        min_names=min_names,
    )
