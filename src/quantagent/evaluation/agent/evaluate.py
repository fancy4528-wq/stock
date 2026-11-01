"""Agent score IC and confidence calibration (docs/08 §6.3–6.4).

Labels are close-to-close forward returns from the decision date, with the
same untradeable-entry mask as factor labels. Cross-sectional Spearman is
unchanged if the day's mean return is subtracted, so IC uses the raw forward
return. A directional hit uses the cross-sectional excess: a score above 0.5
is a bullish call and should beat the day's scored names.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import polars as pl
from scipy import stats  # type: ignore[import-untyped]

from quantagent.evaluation.agent.types import AgentEvalResult, AgentScoreDay, CalibrationResult
from quantagent.quant.evaluation.ic import daily_ic_series, summarize_ic
from quantagent.quant.evaluation.types import ICSummary
from quantagent.quant.labels.targets import attach_forward_returns
from quantagent.shared.errors import QuantAgentError

BUCKET_ORDER: tuple[str, ...] = ("0.0-0.5", "0.5-0.7", "0.7-0.85", "0.85-1.0")
_MIN_NAMES = 3
_MIN_IC_DAYS_FOR_WEIGHT = 20


class AgentEvalError(QuantAgentError):
    """Agent IC inputs are missing or unusable."""


def confidence_bucket(confidence: float) -> str:
    """Map confidence into the docs/08 §6.4 buckets.

    Edges fall in the higher bucket: 0.5 → ``0.5-0.7``, 0.7 → ``0.7-0.85``,
    0.85 → ``0.85-1.0``.
    """
    c = float(confidence)
    if c < 0.5:
        return "0.0-0.5"
    if c < 0.7:
        return "0.5-0.7"
    if c < 0.85:
        return "0.7-0.85"
    return "0.85-1.0"


def check_calibration(
    confidences: Sequence[float],
    hits: Sequence[bool],
) -> CalibrationResult:
    """Hit rate by confidence bucket.

    ``hits[i]`` is whether that view's directional call was correct.
    Slope is the OLS slope of hit (0/1) on confidence; 1.0 means confidence
    is a calibrated probability of being correct. Monotonic is True when
    populated buckets rise with confidence. Fewer than two populated buckets
    leaves monotonic unset.
    """
    if len(confidences) != len(hits):
        raise AgentEvalError("confidences and hits must have the same length")

    grouped: dict[str, list[float]] = {name: [] for name in BUCKET_ORDER}
    conf_arr: list[float] = []
    hit_arr: list[float] = []
    for confidence, hit in zip(confidences, hits, strict=True):
        grouped[confidence_bucket(confidence)].append(1.0 if hit else 0.0)
        conf_arr.append(float(confidence))
        hit_arr.append(1.0 if hit else 0.0)

    hit_rate = {name: float(np.mean(vals)) for name, vals in grouped.items() if vals}
    counts = {name: len(vals) for name, vals in grouped.items() if vals}
    ordered = [hit_rate[name] for name in BUCKET_ORDER if name in hit_rate]
    if len(ordered) < 2:
        monotonic: bool | None = None
    else:
        monotonic = all(b >= a - 1e-12 for a, b in zip(ordered, ordered[1:], strict=False))

    slope: float | None = None
    if len(conf_arr) >= 2 and float(np.std(conf_arr)) > 1e-15:
        fitted = stats.linregress(np.asarray(conf_arr), np.asarray(hit_arr))
        if fitted.slope is not None and not np.isnan(fitted.slope):
            slope = float(fitted.slope)

    return CalibrationResult(
        hit_rate_by_bucket=hit_rate,
        n_by_bucket=counts,
        slope=slope,
        monotonic=monotonic,
        n=len(conf_arr),
    )


def _pack_ic(summary: ICSummary) -> tuple[float | None, float | None, int]:
    if summary.n_periods == 0:
        return None, None, 0
    t_stat = summary.ic_t_stat if summary.n_periods > 1 and summary.ic_std > 1e-15 else None
    return summary.ic_mean, t_stat, summary.n_periods


def _ranking_ic(panel: pl.DataFrame) -> float | None:
    """Pooled Spearman of within-day score ranks vs within-day return ranks.

    Days with fewer than three names are left out. This is size-weighted,
    so it can differ from the equal-weighted mean of daily score IC.
    """
    clean = panel.select(["trade_date", "score", "fwd_ret_5d"]).drop_nulls()
    if clean.is_empty():
        return None
    counts = clean.group_by("trade_date").agg(pl.len().alias("_n"))
    keep_dates = counts.filter(pl.col("_n") >= _MIN_NAMES).select("trade_date")
    clean = clean.join(keep_dates, on="trade_date", how="inner")
    if clean.height < _MIN_NAMES:
        return None
    ranked = clean.with_columns(
        pl.col("score").rank(method="average").over("trade_date").alias("_rs"),
        pl.col("fwd_ret_5d").rank(method="average").over("trade_date").alias("_rr"),
    )
    pairs = ranked.select(["_rs", "_rr"]).drop_nulls()
    if pairs.height < _MIN_NAMES:
        return None
    xv = pairs["_rs"].to_numpy()
    yv = pairs["_rr"].to_numpy()
    if np.nanstd(xv) < 1e-15 or np.nanstd(yv) < 1e-15:
        return None
    corr, _ = stats.spearmanr(xv, yv)
    if corr is None or np.isnan(corr):
        return None
    return float(corr)


def _interpret(
    *,
    n_ic_days_5d: int,
    score_ic_5d: float | None,
    score_ic_t_stat: float | None,
    calibration_monotonic: bool | None,
    calibration_slope: float | None,
) -> str:
    parts: list[str] = []
    if score_ic_5d is None:
        parts.append("5日收益标签尚未齐，IC 未测出。")
    elif n_ic_days_5d < _MIN_IC_DAYS_FOR_WEIGHT:
        parts.append(
            f"5日 IC 有效截面 {n_ic_days_5d} 天，少于 {_MIN_IC_DAYS_FOR_WEIGHT}，"
            "数字只作跟踪，不能作为降权依据。"
        )
    elif abs(score_ic_5d) < 0.02 and abs(score_ic_t_stat or 0.0) < 2.0:
        parts.append(
            "5日 IC 接近 0。按 docs/08 §6.5，不要为刷正 IC 调 prompt；"
            "Agent 在 Fusion 中的权重应降低或置零，保留解释与风险识别。"
        )
    else:
        parts.append("5日 IC 已测出。不要为改变符号反复调 prompt；结论随前向窗口更新。")

    if calibration_monotonic is False:
        parts.append(
            "准确率没有随 confidence 档上升。confidence 只反映语言自信，Fusion 应忽略该字段。"
        )
    elif calibration_monotonic is True:
        slope_txt = "—" if calibration_slope is None else f"{calibration_slope:.2f}"
        parts.append(f"准确率随 confidence 档上升。校准斜率 {slope_txt}（理想 1.0）。")
    else:
        parts.append("confidence 分档样本不足，校准尚未完成。")
    return "".join(parts)


def _as_date_frame(prices: pl.DataFrame) -> pl.DataFrame:
    required = {"symbol", "trade_date", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise AgentEvalError(f"prices missing columns: {sorted(missing)}")
    extra = [c for c in ("is_limit_up", "is_suspended") if c in prices.columns]
    frame = prices.select(["symbol", "trade_date", "close", *extra])
    dtype = frame.schema["trade_date"]
    if dtype in (pl.String, pl.Utf8):
        frame = frame.with_columns(pl.col("trade_date").str.to_date())
    elif dtype == pl.Datetime or str(dtype).startswith("Datetime"):
        frame = frame.with_columns(pl.col("trade_date").dt.date())
    return frame


def _score_frame(days: Sequence[AgentScoreDay]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for day in days:
        by_symbol: dict[str, tuple[float, float]] = {}
        for point in day.points:
            by_symbol[point.symbol] = (point.score, point.confidence)
        for symbol, (score, confidence) in by_symbol.items():
            rows.append(
                {
                    "trade_date": day.as_of,
                    "symbol": symbol,
                    "score": score,
                    "confidence": confidence,
                }
            )
    if not rows:
        raise AgentEvalError("agent score days have no points")
    return pl.DataFrame(rows).with_columns(pl.col("trade_date").cast(pl.Date))


def _with_hits(panel: pl.DataFrame) -> pl.DataFrame:
    """Directional hit vs same-day excess return. Neutral scores are null."""
    labeled = panel.filter(pl.col("fwd_ret_5d").is_not_null())
    if labeled.is_empty():
        return panel.with_columns(pl.lit(None).cast(pl.Float64).alias("hit_5d"))
    means = labeled.group_by("trade_date").agg(pl.col("fwd_ret_5d").mean().alias("_mkt"))
    out = panel.join(means, on="trade_date", how="left")
    excess = pl.col("fwd_ret_5d") - pl.col("_mkt")
    bullish = pl.col("score") - 0.5
    hit = (
        pl.when(pl.col("fwd_ret_5d").is_null() | (bullish == 0) | (excess == 0))
        .then(None)
        .when(bullish * excess > 0)
        .then(1.0)
        .otherwise(0.0)
    )
    return out.with_columns(hit.alias("hit_5d")).drop("_mkt")


def evaluate_agent_scores(
    days: Sequence[AgentScoreDay],
    prices: pl.DataFrame,
    *,
    agent_name: str | None = None,
    include_synthetic: bool = False,
) -> AgentEvalResult:
    """Join recorded scores to forward returns and summarize IC plus calibration.

    Synthetic daily-report rows are dropped unless ``include_synthetic`` is set.
    They share the shadow directory with live scores and are not Agent forecasts.
    """
    if not include_synthetic:
        days = [day for day in days if day.origin != "synthetic"]
    if not days:
        raise AgentEvalError("no live agent score days")
    names = {day.agent_name for day in days}
    resolved_name = agent_name or (next(iter(names)) if len(names) == 1 else "mixed")
    as_ofs = [day.as_of for day in days]
    period = (min(as_ofs), max(as_ofs))
    n_outputs = sum(len({p.symbol for p in day.points}) for day in days)

    scores = _score_frame(days)
    labels = attach_forward_returns(_as_date_frame(prices), horizons=(5, 20), price_col="close")
    label_cols = labels.select(["symbol", "trade_date", "fwd_ret_5d", "fwd_ret_20d"])
    panel = _with_hits(scores.join(label_cols, on=["symbol", "trade_date"], how="left"))

    n_labeled_5d = panel.filter(pl.col("fwd_ret_5d").is_not_null()).height
    n_labeled_20d = panel.filter(pl.col("fwd_ret_20d").is_not_null()).height

    ic5_frame = daily_ic_series(panel, factor_col="score", return_col="fwd_ret_5d")
    ic20_frame = daily_ic_series(panel, factor_col="score", return_col="fwd_ret_20d")
    ic5, t5, n5 = _pack_ic(summarize_ic(ic5_frame["ic"] if not ic5_frame.is_empty() else []))
    ic20, t20, n20 = _pack_ic(summarize_ic(ic20_frame["ic"] if not ic20_frame.is_empty() else []))

    hits = panel.filter(pl.col("hit_5d").is_not_null())
    calibration = check_calibration(
        hits["confidence"].to_list(),
        [bool(v) for v in hits["hit_5d"].to_list()],
    )
    text = _interpret(
        n_ic_days_5d=n5,
        score_ic_5d=ic5,
        score_ic_t_stat=t5,
        calibration_monotonic=calibration.monotonic,
        calibration_slope=calibration.slope,
    )
    return AgentEvalResult(
        agent_name=resolved_name,
        period=period,
        n_outputs=n_outputs,
        n_days=len({day.as_of for day in days}),
        n_labeled_5d=n_labeled_5d,
        n_labeled_20d=n_labeled_20d,
        n_ic_days_5d=n5,
        n_ic_days_20d=n20,
        score_ic_5d=ic5,
        score_ic_20d=ic20,
        score_ic_t_stat=t5,
        score_ic_20d_t_stat=t20,
        ranking_ic=_ranking_ic(panel),
        confidence_calibration=calibration.hit_rate_by_bucket,
        calibration_n=calibration.n_by_bucket,
        calibration_slope=calibration.slope,
        calibration_monotonic=calibration.monotonic,
        interpretation=text,
    )
