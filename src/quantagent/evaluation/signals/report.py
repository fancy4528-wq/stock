"""Markdown for the signal-independence check."""

from __future__ import annotations

from pathlib import Path

from quantagent.evaluation.signals.types import SignalCorrResult, SignalPairCorr

_FLAG = {"ok": "未超阈值", "merge": "应合并", "tracking": "跟踪"}


def _num(value: float | None, spec: str = "+.3f") -> str:
    if value is None:
        return "—"
    return format(value, spec)


def _pair_row(pair: SignalPairCorr) -> str:
    return (
        f"| {pair.left} | {pair.right} | {pair.corr:+.3f} | {pair.n_days} | "
        f"{pair.mean_names:.1f} | {_FLAG[pair.flag]} |"
    )


def render_signal_corr_report(result: SignalCorrResult) -> str:
    if result.period is None:
        window = "无 live 截面"
    else:
        start, end = result.period
        window = f"{start.isoformat()} → {end.isoformat()}"
    signals = "、".join(result.signals) if result.signals else "—"
    missing = "、".join(result.missing_fusion_slots) if result.missing_fusion_slots else "无"
    pair_rows = [_pair_row(pair) for pair in result.pairs] or [
        "| — | — | — | 0 | — | — |"
    ]
    ic_rows: list[str] = []
    for stat in result.ics:
        ic_rows.append(
            f"| {stat.signal} | {stat.horizon} | {_num(stat.ic_mean, '+.4f')} | "
            f"{_num(stat.ic_t_stat)} | {stat.n_days} |"
        )
    if not ic_rows:
        ic_rows.append("| — | — | — | — | 0 |")
    changed = "是" if result.weights_changed else "否"
    return "\n".join(
        [
            "# 信号相关矩阵",
            "",
            f"> 前向记录 {window}",
            "> 日截面 Spearman 的等权平均。重叠标的少于 5 只的日子不计入。"
            "绝对相关 > 0.7 且有效天数 ≥ 20 才标「应合并」。不足 20 天只跟踪，不改 Fusion 权重。",
            "",
            "## 样本",
            "",
            "| 项 | 值 |",
            "|---|---|",
            f"| live 截面天数 | {result.n_days} |",
            f"| 已记录信号 | {signals} |",
            f"| Fusion 槽位尚未产出 | {missing} |",
            f"| 本次是否修改权重 | {changed} |",
            "",
            "## 相关",
            "",
            "| 信号 A | 信号 B | 平均 Spearman | 天数 | 平均重叠数 | 标记 |",
            "|---|---|---:|---:|---:|---|",
            *pair_rows,
            "",
            "## 单独 IC",
            "",
            "未传价格面板时本节为空。IC 用决策日分数对收盘到收盘的远期收益，与因子标签同一口径。",
            "",
            "| 信号 | 期限 | IC | t | 截面天数 |",
            "|---|---|---:|---:|---:|",
            *ic_rows,
            "",
            "## 读法",
            "",
            result.interpretation,
            "",
        ]
    )


def write_signal_corr_report(result: SignalCorrResult, path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_signal_corr_report(result), encoding="utf-8")
    return out
