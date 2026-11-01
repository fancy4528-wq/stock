"""Markdown for the monthly self-evaluation."""

from __future__ import annotations

from pathlib import Path

from quantagent.evaluation.agent.evaluate import BUCKET_ORDER
from quantagent.evaluation.review.types import FactorHealth, MonthlyReview, ShadowMonthRow

_FACTOR_STATUS = {"healthy": "健康", "weakening": "衰减", "unknown": "未观测"}
_PAIR_FLAG = {"ok": "未超阈值", "merge": "应合并", "tracking": "跟踪"}


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:+.2%}"
    if text in {"+0.00%", "-0.00%"}:
        return "0.00%"
    return text


def _num(value: float | None, spec: str = "+.4f") -> str:
    if value is None:
        return "—"
    return format(value, spec)


def _date(value: object) -> str:
    if value is None:
        return "—"
    return str(value)


def _shadow_row(row: ShadowMonthRow) -> str:
    return (
        f"| {row.portfolio} | {row.n_days} | {_date(row.start)} | {_date(row.end)} | "
        f"{_pct(row.ret_month)} | {_pct(row.ret_cum)} | {_pct(row.max_drawdown)} | "
        f"{row.n_unfilled} |"
    )


def _factor_row(row: FactorHealth) -> str:
    return (
        f"| {row.factor} | {_num(row.hist_ic)} | {_num(row.recent_ic)} | "
        f"{_num(row.decay_ratio, '+.3f')} | {_FACTOR_STATUS[row.status]} |"
    )


def render_monthly_review(review: MonthlyReview) -> str:
    start, end = review.period
    shadow_rows = [_shadow_row(row) for row in review.shadows] or [
        "| — | 0 | — | — | — | — | — | 0 |"
    ]
    warning_lines = [f"- {line}" for line in review.shadow_warnings]
    pair_rows = [
        (
            f"| {pair.left} | {pair.right} | {pair.corr:+.3f} | {pair.n_days} | "
            f"{_PAIR_FLAG[pair.flag]} |"
        )
        for pair in review.signals.pairs
    ] or ["| — | — | — | 0 | — |"]
    ic_rows = [
        (
            f"| {stat.signal} | {stat.horizon} | {_num(stat.ic_mean)} | "
            f"{_num(stat.ic_t_stat, '+.3f')} | {stat.n_days} |"
        )
        for stat in review.signals.ics
    ] or ["| — | — | — | — | 0 |"]
    factor_rows = [_factor_row(row) for row in review.factors]
    if review.agent is None:
        agent_block = ["本次未附带 AgentEvalResult。", "", review.agent_note]
    else:
        agent = review.agent
        buckets = []
        for name in BUCKET_ORDER:
            if name not in agent.confidence_calibration:
                continue
            buckets.append(
                f"| {name} | {agent.calibration_n.get(name, 0)} | "
                f"{agent.confidence_calibration[name]:.1%} |"
            )
        if not buckets:
            buckets.append("| — | 0 | — |")
        agent_block = [
            f"前向窗口 {agent.period[0].isoformat()} → {agent.period[1].isoformat()}，"
            f"5 日 IC 截面 {agent.n_ic_days_5d} 天。",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| score IC 5d | {_num(agent.score_ic_5d)} |",
            f"| score IC 20d | {_num(agent.score_ic_20d)} |",
            f"| 5 日 IC 截面天数 | {agent.n_ic_days_5d} |",
            f"| 校准斜率 | {_num(agent.calibration_slope, '+.3f')} |",
            "",
            "| 档 | 条数 | 5日方向命中率 |",
            "|---|---|---|",
            *buckets,
            "",
            agent.interpretation,
            "",
            review.agent_note,
        ]
    if review.conditions:
        condition_rows = [
            f"| {row.condition} | {row.n} | {_pct(row.accuracy_5d)} |"
            for row in review.conditions
        ]
    else:
        condition_rows = ["| — | 0 | — |"]
    alloc_rows = [
        f"| {name} | ${amount:.4f} |" for name, amount in review.costs.by_allocation.items()
    ] or ["| — | — |"]
    alert_lines = [f"- {line}" for line in review.alerts]
    changed = "是" if review.signals.weights_changed else "否"
    cost_lines = [
        f"LLM 成本日志在本月命中 {review.costs.n_rows} 行，合计 ${review.costs.usd:.4f}。",
    ]
    if review.costs.note:
        cost_lines.append(review.costs.note)
    return "\n".join(
        [
            f"# 月度自评 {review.month}",
            "",
            f"> {start.isoformat()} → {end.isoformat()}",
            "> 读已落盘的 shadow、信号截面、Agent 前向记录和成本日志。"
            f"本次是否修改 Fusion 权重：{changed}。",
            "",
            "## 1. 整体表现",
            "",
            "月收益是该月 `ret_1d` 的复利。自启动累计是月末最后一条 `ret_cum`。"
            "月内回撤只在该月净值序列上计算。",
            "",
            "| 组合 | 天数 | 起 | 止 | 月收益 | 自启动累计 | 月内回撤 | 未成交 |",
            "|---|---:|---|---|---:|---:|---:|---:|",
            *shadow_rows,
            *(["", *warning_lines] if warning_lines else []),
            "",
            "## 2. 信号有效性",
            "",
            review.signals.interpretation,
            "",
            "| 信号 A | 信号 B | 平均 Spearman | 天数 | 标记 |",
            "|---|---|---:|---:|---|",
            *pair_rows,
            "",
            "| 信号 | 期限 | IC | t | 截面天数 |",
            "|---|---|---:|---:|---:|",
            *ic_rows,
            "",
            "## 3. 因子健康度",
            "",
            review.factor_note,
            "",
            "| 因子 | 冻结 IC | 近期 IC | decay_ratio | 状态 |",
            "|---|---:|---:|---:|---|",
            *factor_rows,
            "",
            "## 4. Agent 质量",
            "",
            *agent_block,
            "",
            "## 5. 分条件准确率",
            "",
            "决策日志还没有 market_regime、波动率或事件条件标签，本节无数字。"
            if not review.conditions
            else "条件来自调用方传入的决策结果，本报告不自行查询。",
            "",
            "| 条件 | 条数 | 5日方向命中率 |",
            "|---|---:|---:|",
            *condition_rows,
            "",
            "## 6. 失效告警",
            "",
            *alert_lines,
            "",
            "## 7. 成本分析",
            "",
            review.trading_cost_note,
            "",
            *cost_lines,
            "",
            "| 预算池 | USD |",
            "|---|---:|",
            *alloc_rows,
            "",
        ]
    )


def write_monthly_review(review: MonthlyReview, path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_monthly_review(review), encoding="utf-8")
    return out
