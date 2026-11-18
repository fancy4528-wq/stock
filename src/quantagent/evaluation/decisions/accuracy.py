"""Condition accuracy for monthly review §5 (docs/08 §8.1).

Joins append-only decision context tags to Agent directional hits. Does not
edit Fusion weights. Sample counts stay visible even when forward labels are
not yet available; accuracy stays null until hits exist.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from quantagent.evaluation.agent.evaluate import (
    AgentEvalError,
    _as_date_frame,
    _score_frame,
    _with_hits,
)
from quantagent.evaluation.agent.types import AgentScoreDay
from quantagent.evaluation.decisions.types import DecisionContextDay
from quantagent.quant.labels.targets import attach_forward_returns

if TYPE_CHECKING:
    from quantagent.evaluation.review.types import ConditionAccuracy

_REGIME_PREFIX = "regime:"
_VOL_PREFIX = "vol:"
_EVENT_PREFIX = "event:"


def _in_month(day: date, *, start: date, end: date) -> bool:
    return start <= day <= end


def _condition_keys(ctx: DecisionContextDay) -> list[str]:
    keys = [
        f"{_REGIME_PREFIX}{ctx.market_regime}",
        f"{_VOL_PREFIX}{ctx.volatility}",
    ]
    keys.extend(f"{_EVENT_PREFIX}{tag}" for tag in ctx.event_tags)
    return keys


def condition_accuracy(
    contexts: Sequence[DecisionContextDay],
    score_days: Sequence[AgentScoreDay],
    prices: pl.DataFrame | None,
    *,
    start: date,
    end: date,
    include_synthetic: bool = False,
) -> tuple[list[ConditionAccuracy], str]:
    """Bucket Agent 5d directional hits by the day's stored conditions.

    Returns ``(rows, note)``. ``note`` explains empty or unlabeled states.
    """
    # Runtime import: review.__init__ pulls monthly, which imports this module.
    from quantagent.evaluation.review.types import ConditionAccuracy

    if not include_synthetic:
        contexts = [c for c in contexts if c.origin != "synthetic"]
        score_days = [d for d in score_days if d.origin != "synthetic"]

    month_ctx = [c for c in contexts if _in_month(c.as_of, start=start, end=end)]
    if not month_ctx:
        return [], "决策日志还没有 market_regime、波动率或事件条件标签，本节无数字。"

    by_as_of = {c.as_of: c for c in month_ctx}
    day_counts: dict[str, int] = defaultdict(int)
    for ctx in month_ctx:
        for key in _condition_keys(ctx):
            day_counts[key] += 1

    if prices is None:
        rows = [
            ConditionAccuracy(condition=key, n=n, accuracy_5d=None)
            for key, n in sorted(day_counts.items())
        ]
        return rows, (
            f"已记录 {len(month_ctx)} 个交易日的条件标签；"
            "未提供行情，5 日方向命中率尚未计算。"
        )

    month_scores = [
        d for d in score_days if _in_month(d.as_of, start=start, end=end) and d.as_of in by_as_of
    ]
    if not month_scores:
        rows = [
            ConditionAccuracy(condition=key, n=n, accuracy_5d=None)
            for key, n in sorted(day_counts.items())
        ]
        return rows, (
            f"已记录 {len(month_ctx)} 个交易日的条件标签；"
            "同窗没有可配对的 Agent 打分，命中率留空。"
        )

    try:
        scores = _score_frame(month_scores)
        labels = attach_forward_returns(
            _as_date_frame(prices), horizons=(5,), price_col="close"
        )
        panel = _with_hits(
            scores.join(
                labels.select(["symbol", "trade_date", "fwd_ret_5d"]),
                on=["symbol", "trade_date"],
                how="left",
            )
        )
    except AgentEvalError as exc:
        rows = [
            ConditionAccuracy(condition=key, n=n, accuracy_5d=None)
            for key, n in sorted(day_counts.items())
        ]
        return rows, f"条件标签已记录，但命中率未算出：{exc}"

    hits = panel.filter(pl.col("hit_5d").is_not_null())
    if hits.is_empty():
        rows = [
            ConditionAccuracy(condition=key, n=n, accuracy_5d=None)
            for key, n in sorted(day_counts.items())
        ]
        return rows, (
            f"已记录 {len(month_ctx)} 个交易日的条件标签；"
            "5 日收益标签尚未齐，命中率留空。"
        )

    hit_sums: dict[str, float] = defaultdict(float)
    hit_ns: dict[str, int] = defaultdict(int)
    for row in hits.iter_rows(named=True):
        ctx = by_as_of.get(row["trade_date"])
        if ctx is None:
            continue
        hit = float(row["hit_5d"])
        for key in _condition_keys(ctx):
            hit_sums[key] += hit
            hit_ns[key] += 1

    rows: list[ConditionAccuracy] = []
    for key in sorted(day_counts):
        n_hits = hit_ns.get(key, 0)
        accuracy = (hit_sums[key] / n_hits) if n_hits else None
        rows.append(
            ConditionAccuracy(
                condition=key,
                n=n_hits if n_hits else day_counts[key],
                accuracy_5d=accuracy,
            )
        )
    labeled_days = len({row["trade_date"] for row in hits.iter_rows(named=True)})
    return rows, (
        f"条件来自 decision_context 日记；"
        f"{labeled_days}/{len(month_ctx)} 个交易日已有 5 日方向命中样本。"
        "本报告不改 Fusion 权重。"
    )
