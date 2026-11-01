"""Markdown report for Agent IC and confidence calibration."""

from __future__ import annotations

from pathlib import Path

from quantagent.evaluation.agent.evaluate import BUCKET_ORDER
from quantagent.evaluation.agent.types import AgentEvalResult


def _num(value: float | None, spec: str = "+.4f") -> str:
    if value is None:
        return "—"
    return format(value, spec)


def render_agent_eval_report(result: AgentEvalResult) -> str:
    start, end = result.period
    bucket_rows = []
    for name in BUCKET_ORDER:
        if name not in result.confidence_calibration:
            continue
        n = result.calibration_n.get(name, 0)
        rate = result.confidence_calibration[name]
        bucket_rows.append(f"| {name} | {n} | {rate:.1%} |")
    if not bucket_rows:
        bucket_rows.append("| — | 0 | — |")
    mono = {True: "是", False: "否", None: "样本不足"}.get(result.calibration_monotonic, "样本不足")
    return "\n".join(
        [
            f"# Agent IC / Confidence 校准 `{result.agent_name}`",
            "",
            f"> 前向记录 {start.isoformat()} → {end.isoformat()}",
            "> 分数取决策日原始 score，不回放 LLM。5 日命中：score>0.5 视为看多，"
            "超额为当日已打分标的的截面均值。",
            "",
            "## 样本",
            "",
            "| 项 | 值 |",
            "|---|---|",
            f"| 决策日 | {result.n_days} |",
            f"| 打分条数 | {result.n_outputs} |",
            f"| 有 5 日收益 | {result.n_labeled_5d} |",
            f"| 有 20 日收益 | {result.n_labeled_20d} |",
            f"| 5 日 IC 截面天数 | {result.n_ic_days_5d} |",
            f"| 20 日 IC 截面天数 | {result.n_ic_days_20d} |",
            "",
            "## IC",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| score IC 5d（截面 Spearman 均值） | {_num(result.score_ic_5d)} |",
            f"| score IC 20d | {_num(result.score_ic_20d)} |",
            f"| score IC t-stat（5d） | {_num(result.score_ic_t_stat, '+.3f')} |",
            f"| score IC t-stat（20d） | {_num(result.score_ic_20d_t_stat, '+.3f')} |",
            f"| ranking IC（按日样本加权的秩相关） | {_num(result.ranking_ic)} |",
            "",
            "## Confidence 校准",
            "",
            "| 档 | 条数 | 5日方向命中率 |",
            "|---|---|---|",
            *bucket_rows,
            "",
            "| 项 | 值 |",
            "|---|---|",
            f"| 校准斜率（理想 1.0） | {_num(result.calibration_slope, '+.3f')} |",
            f"| 命中率随档位上升 | {mono} |",
            "",
            "## 读法",
            "",
            result.interpretation,
            "",
        ]
    )


def write_agent_eval_report(result: AgentEvalResult, path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_agent_eval_report(result), encoding="utf-8")
    return out
