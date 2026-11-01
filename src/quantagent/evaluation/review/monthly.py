"""Assemble one monthly self-evaluation (docs/08 §8.2).

The report reads journals already on disk. It does not re-score factors, replay
an LLM, or edit Fusion weights. Regime accuracy stays empty until a decision
journal stores those labels.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from quantagent.evaluation.agent.types import AgentEvalResult
from quantagent.evaluation.review.costs import summarize_cost_log
from quantagent.evaluation.review.factors import assess_admitted_factors
from quantagent.evaluation.review.shadows import PORTFOLIOS, load_shadow_month
from quantagent.evaluation.review.types import (
    ConditionAccuracy,
    CostSummary,
    FactorHealth,
    MonthlyReview,
)
from quantagent.evaluation.signals.correlation import check_signal_independence
from quantagent.evaluation.signals.journal import load_signal_score_days
from quantagent.evaluation.signals.types import (
    MIN_DAYS_FOR_ACTION,
    SignalCorrResult,
    SignalScoreDay,
)

_BACKTEST_NOTE = (
    "影子日记只记未成交笔数，不记佣金、印花税、过户费和滑点。"
    "组合级成本以 docs/backtest-reports/l2_equal_topn-csi300-5y.md 第 5 节为准。"
)
_FACTOR_NOTE = (
    "历史 IC 是 2026-10-14 冻结的 CSI300 五年准入值，只用于对照。"
    "没有近期因子面板时不计算 decay_ratio，不标 weakening，也不因此降权。"
)


def month_bounds(month: str) -> tuple[date, date]:
    """``YYYY-MM`` → first and last calendar day."""
    year_text, month_text = month.split("-", 1)
    year, month_num = int(year_text), int(month_text)
    last = calendar.monthrange(year, month_num)[1]
    return date(year, month_num, 1), date(year, month_num, last)


def _alerts(
    *,
    signals: SignalCorrResult,
    agent: AgentEvalResult | None,
    factors: Sequence[FactorHealth],
    ever_seen: set[str],
    month_days: int,
) -> list[str]:
    notes: list[str] = []
    if month_days == 0:
        notes.append("该月六个 shadow 组合都没有记录。")
    missing = [name for name in PORTFOLIOS if name not in ever_seen]
    if missing:
        notes.append("自启动以来仍无记录：" + "、".join(missing) + "。")
    if signals.n_days == 0:
        notes.append("没有 live 信号截面，相关矩阵未算出。不改 Fusion 权重。")
    elif signals.n_days < MIN_DAYS_FOR_ACTION or any(
        pair.flag == "tracking" for pair in signals.pairs
    ):
        notes.append(
            f"信号相关有效天数不足 {MIN_DAYS_FOR_ACTION}，只跟踪，不合并，不改 Fusion 权重。"
        )
    for pair in signals.pairs:
        if pair.flag == "merge":
            notes.append(
                f"{pair.left}/{pair.right} 平均相关 {pair.corr:+.3f}"
                f"（{pair.n_days} 天）超过 0.7，应合并。本次不改 Fusion 权重。"
            )
    if agent is None:
        notes.append("Agent IC 未在本报告重算。有效截面不足 20 天之前不降权。")
    elif agent.n_ic_days_5d < MIN_DAYS_FOR_ACTION:
        notes.append(
            f"Agent 5 日 IC 有效截面 {agent.n_ic_days_5d} 天，少于 {MIN_DAYS_FOR_ACTION}，不降权。"
        )
    for row in factors:
        if row.status == "weakening":
            notes.append(f"因子 {row.factor} 近期 IC 相对冻结值衰减或变号，标为 weakening。")
    if not notes:
        notes.append("本月没有新增的失效标记。Fusion 权重未被本报告修改。")
    return notes


def build_monthly_review(
    *,
    month: str,
    shadow_dir: Path | str,
    cost_log_text: str | None = None,
    signal_days: Sequence[SignalScoreDay] | None = None,
    prices: object | None = None,
    include_synthetic_signals: bool = False,
    agent: AgentEvalResult | None = None,
    agent_note: str = "",
    recent_factor_ic: dict[str, float] | None = None,
    conditions: Sequence[ConditionAccuracy] | None = None,
) -> MonthlyReview:
    """Build the seven sections from journals. ``prices`` is an optional Polars frame."""
    import polars as pl

    start, end = month_bounds(month)
    shadows, warnings, ever_seen = load_shadow_month(shadow_dir, start=start, end=end)
    days = (
        list(signal_days)
        if signal_days is not None
        else load_signal_score_days(shadow_dir)
    )
    frame = prices if isinstance(prices, pl.DataFrame) else None
    signals = check_signal_independence(
        days,
        prices=frame,
        include_synthetic=include_synthetic_signals,
    )
    factors = assess_admitted_factors(recent_factor_ic)
    factor_note = _FACTOR_NOTE
    if recent_factor_ic:
        factor_note = (
            "历史 IC 是 2026-10-14 冻结的 CSI300 五年准入值。"
            "近期 IC 由调用方传入，本报告不重新估计因子。"
        )
    if cost_log_text is None:
        costs = CostSummary(note="未提供成本日志。")
    else:
        costs = summarize_cost_log(cost_log_text, start=start, end=end)
    note = agent_note
    if agent is None and not note:
        note = "本次没有重算 Agent IC。有效截面不足 20 天之前不降权。"
    month_days = sum(row.n_days for row in shadows)
    return MonthlyReview(
        month=month,
        period=(start, end),
        shadows=shadows,
        shadow_warnings=warnings,
        signals=signals,
        agent=agent,
        agent_note=note,
        factors=factors,
        factor_note=factor_note,
        conditions=list(conditions or []),
        alerts=_alerts(
            signals=signals,
            agent=agent,
            factors=factors,
            ever_seen=ever_seen,
            month_days=month_days,
        ),
        costs=costs,
        trading_cost_note=_BACKTEST_NOTE,
    )
