"""Pairwise signal correlation and standalone IC (docs/08 §7.3).

Daily Spearman is averaged with equal weight per day. A pair is ``merge`` only
when the mean absolute correlation is above 0.7 and at least 20 days contributed.
Shorter windows stay ``tracking``. Nothing here writes a new Fusion weight.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

import polars as pl

from quantagent.evaluation.signals.types import (
    FUSION_SLOTS,
    MERGE_ABS_CORR,
    MIN_DAYS_FOR_ACTION,
    MIN_NAMES,
    SIGNAL_ORDER,
    SignalCorrResult,
    SignalICStat,
    SignalPairCorr,
    SignalScoreDay,
)
from quantagent.quant.evaluation.ic import (
    cross_sectional_spearman,
    daily_ic_series,
    summarize_ic,
)
from quantagent.quant.labels.targets import attach_forward_returns
from quantagent.shared.errors import QuantAgentError


class SignalCorrError(QuantAgentError):
    """Signal-correlation inputs are missing or unusable."""


def _ordered(names: set[str]) -> list[str]:
    head = [name for name in SIGNAL_ORDER if name in names]
    tail = sorted(names - set(head))
    return head + tail


def _collapse(days: Sequence[SignalScoreDay]) -> list[SignalScoreDay]:
    by_day: dict[date, SignalScoreDay] = {}
    for day in days:
        by_day[day.as_of] = day
    return [by_day[key] for key in sorted(by_day)]


def _flag(corr: float, n_days: int) -> Literal["ok", "merge", "tracking"]:
    if n_days < MIN_DAYS_FOR_ACTION:
        return "tracking"
    if abs(corr) > MERGE_ABS_CORR:
        return "merge"
    return "ok"


def _interpret(result_pairs: list[SignalPairCorr], n_days: int, signals: list[str]) -> str:
    if n_days == 0 or not signals:
        return (
            "没有 live 信号截面，相关矩阵未算出。"
            "Fusion 权重保持 equal-v1，本次不修改。"
        )
    if not result_pairs:
        return (
            f"有 {n_days} 个 live 截面，但没有一对信号同时覆盖至少 {MIN_NAMES} 只股票。"
            "矩阵未算出。Fusion 权重保持 equal-v1，本次不修改。"
        )
    short = [pair for pair in result_pairs if pair.n_days < MIN_DAYS_FOR_ACTION]
    merges = [pair for pair in result_pairs if pair.flag == "merge"]
    parts: list[str] = []
    if short:
        parts.append(
            f"相关有效天数不足 {MIN_DAYS_FOR_ACTION}，"
            "数字只作跟踪，不合并信号，也不改 Fusion 权重。"
        )
    if merges:
        names = "、".join(f"{pair.left}/{pair.right}" for pair in merges)
        parts.append(
            f"{names} 的绝对相关超过 {MERGE_ABS_CORR:.1f}，等权会把同一信息加两次，应合并。"
            "本次运行不修改 FusionConfig。"
        )
    if not short and not merges:
        parts.append(
            f"已记录信号的绝对相关都不超过 {MERGE_ABS_CORR:.1f}。"
            "这不自动确认 Fusion 权重，本次运行也不修改它们。"
        )
    return "".join(parts)


def _pair_stats(
    days: Sequence[SignalScoreDay],
    left: str,
    right: str,
) -> SignalPairCorr | None:
    corrs: list[float] = []
    widths: list[int] = []
    for day in days:
        a = day.signals.get(left) or {}
        b = day.signals.get(right) or {}
        overlap = [symbol for symbol in a if symbol in b]
        if len(overlap) < MIN_NAMES:
            continue
        corr = cross_sectional_spearman(
            pl.Series("x", [a[symbol] for symbol in overlap]),
            pl.Series("y", [b[symbol] for symbol in overlap]),
        )
        if corr is None:
            continue
        corrs.append(corr)
        widths.append(len(overlap))
    if not corrs:
        return None
    mean = sum(corrs) / len(corrs)
    return SignalPairCorr(
        left=left,
        right=right,
        corr=mean,
        n_days=len(corrs),
        mean_names=sum(widths) / len(widths),
        flag=_flag(mean, len(corrs)),
    )


def _price_frame(prices: pl.DataFrame) -> pl.DataFrame:
    required = {"symbol", "trade_date", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise SignalCorrError(f"prices missing columns: {sorted(missing)}")
    frame = prices.select(["symbol", "trade_date", "close"])
    dtype = frame.schema["trade_date"]
    if dtype in (pl.String, pl.Utf8):
        frame = frame.with_columns(pl.col("trade_date").str.to_date())
    elif dtype == pl.Datetime or str(dtype).startswith("Datetime"):
        frame = frame.with_columns(pl.col("trade_date").dt.date())
    return frame


def _standalone_ic(
    days: Sequence[SignalScoreDay],
    prices: pl.DataFrame,
) -> list[SignalICStat]:
    rows: list[dict[str, object]] = []
    for day in days:
        for name, cross in day.signals.items():
            for symbol, score in cross.items():
                rows.append(
                    {
                        "trade_date": day.as_of,
                        "symbol": symbol,
                        "signal": name,
                        "score": float(score),
                    }
                )
    if not rows:
        return []
    frame = pl.DataFrame(rows).with_columns(pl.col("trade_date").cast(pl.Date))
    labels = attach_forward_returns(_price_frame(prices), horizons=(5, 20), price_col="close")
    joined = frame.join(
        labels.select(["symbol", "trade_date", "fwd_ret_5d", "fwd_ret_20d"]),
        on=["symbol", "trade_date"],
        how="left",
    )
    out: list[SignalICStat] = []
    names = {str(item) for item in frame.get_column("signal").unique().to_list()}
    for name in _ordered(names):
        panel = joined.filter(pl.col("signal") == name)
        horizons: tuple[tuple[Literal["5d", "20d"], str], ...] = (
            ("5d", "fwd_ret_5d"),
            ("20d", "fwd_ret_20d"),
        )
        for horizon, col in horizons:
            series = daily_ic_series(panel, factor_col="score", return_col=col)
            summary = summarize_ic(series["ic"] if not series.is_empty() else [])
            t_stat = (
                summary.ic_t_stat
                if summary.n_periods > 1 and summary.ic_std > 1e-15
                else None
            )
            out.append(
                SignalICStat(
                    signal=name,
                    horizon=horizon,
                    ic_mean=summary.ic_mean if summary.n_periods else None,
                    ic_t_stat=t_stat,
                    n_days=summary.n_periods,
                )
            )
    return out


def check_signal_independence(
    days: Sequence[SignalScoreDay],
    *,
    prices: pl.DataFrame | None = None,
    include_synthetic: bool = False,
) -> SignalCorrResult:
    """Mean daily Spearman across signal pairs, plus optional standalone IC.

    Synthetic rows are dropped unless ``include_synthetic`` is set. Last row
    for a date wins. ``weights_changed`` is always False.
    """
    if include_synthetic:
        selected = list(days)
    else:
        selected = [day for day in days if day.origin != "synthetic"]
    selected = _collapse(selected)
    names: set[str] = set()
    for day in selected:
        names.update(name for name, scores in day.signals.items() if scores)
    ordered = _ordered(names)
    pairs: list[SignalPairCorr] = []
    for i, left in enumerate(ordered):
        for right in ordered[i + 1 :]:
            pair = _pair_stats(selected, left, right)
            if pair is not None:
                pairs.append(pair)
    ics = _standalone_ic(selected, prices) if prices is not None and selected else []
    period = (selected[0].as_of, selected[-1].as_of) if selected else None
    return SignalCorrResult(
        period=period,
        n_days=len(selected),
        signals=ordered,
        missing_fusion_slots=[slot for slot in FUSION_SLOTS if slot not in names],
        pairs=pairs,
        ics=ics,
        weights_changed=False,
        interpretation=_interpret(pairs, len(selected), ordered),
    )
