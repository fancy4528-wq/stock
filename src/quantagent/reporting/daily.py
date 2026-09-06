"""Markdown daily report renderer (MVP template)."""

from __future__ import annotations

from pathlib import Path

from quantagent.agents.reporter.schema import DailyReport
from quantagent.agents.tools.market import ReportBundle


def _pct(x: float) -> str:
    return f"{x:+.2%}"


def _ok(flag: bool) -> str:
    return "✅" if flag else "❌"


def render_daily_report(report: DailyReport, bundle: ReportBundle) -> str:
    """Render the MVP daily markdown (facts + tables; no buy advice)."""
    m = bundle.market_overview
    lines: list[str] = [
        f"# A股市场日报 {report.as_of.isoformat()}",
        "",
        f"> 数据截止 {report.as_of.isoformat()} 15:00 收盘 | run_id: {report.run_id}",
        "> ⚠️ 本报告由系统自动生成，不构成投资建议",
        "",
        "## 一、市场概况",
        "",
        report.market_summary,
        "",
        "| 指标 | 数值 | 20日分位 |",
        "|---|---|---|",
        (
            f"| 池内涨跌比 | {m.n_up}:{m.n_down} | "
            f"{'' if m.up_down_pctile_20d is None else f'{m.up_down_pctile_20d:.0%}'} |"
        ),
        (
            f"| 池内成交额 | {m.total_amount / 1e8:.1f}亿 | "
            f"{'' if m.amount_pctile_20d is None else f'{m.amount_pctile_20d:.0%}'} |"
        ),
        (
            f"| 池内平均换手 | {m.avg_turnover:.2%} | "
            f"{'' if m.turnover_pctile_20d is None else f'{m.turnover_pctile_20d:.0%}'} |"
        ),
        "",
        "## 二、行业表现（池内标的按申万一级归类）",
        "",
        report.sector_summary,
        "",
        "| 行业 | 标的数 | 平均涨幅 | 5日 | 20日 |",
        "|---|---|---|---|---|",
    ]
    for s in bundle.sectors:
        lines.append(
            f"| {s.industry} | {s.n_names} | {_pct(s.ret_1d)} | "
            f"{_pct(s.ret_5d)} | {_pct(s.ret_20d)} |"
        )
    if not bundle.sectors:
        lines.append("| — | 0 | — | — | — |")

    lines.extend(
        [
            "",
            "## 三、因子表现",
            "",
            report.factor_summary,
            "",
            "| 因子 | 今日多空收益 | 20日IC均值 |",
            "|---|---|---|",
        ]
    )
    for f in bundle.factors:
        ic = "" if f.ic_mean_20d is None else f"{f.ic_mean_20d:+.3f}"
        lines.append(f"| {f.factor} | {_pct(f.long_short_1d)} | {ic} |")
    if not bundle.factors:
        lines.append("| — | — | — |")

    lines.extend(
        [
            "",
            f"## 四、单因子排序（{bundle.factor_rank_name}，Top 5）",
            "",
            "| 排名 | 代码 | 名称 | 因子分位 | 20日涨幅 |",
            "|---|---|---|---|---|",
        ]
    )
    for r in bundle.factor_ranks[:5]:
        lines.append(
            f"| {r.rank} | {r.symbol} | {r.name} | {r.score_pctile:.2f} | {_pct(r.ret_20d)} |"
        )
    if not bundle.factor_ranks:
        lines.append("| — | — | — | — | — |")

    lines.extend(
        [
            "",
            "## 五、Shadow Portfolio 状态",
            "",
            "| 组合 | 今日 | 累计 | 最大回撤 | 持仓数 |",
            "|---|---|---|---|---|",
        ]
    )
    for sh in bundle.shadow:
        lines.append(
            f"| {sh.portfolio} | {_pct(sh.ret_1d)} | {_pct(sh.ret_cum)} | "
            f"{_pct(sh.max_drawdown)} | {sh.n_positions} |"
        )
    if not bundle.shadow:
        lines.append("| — | — | — | — | — |")

    lines.extend(["", "## 六、风控提示", ""])
    if bundle.risk_notes:
        for n in bundle.risk_notes:
            lines.append(f"- {n.text}")
    else:
        lines.append("- （无触发项）")

    lines.extend(
        [
            "",
            "## 七、数据质量",
            "",
            "| 检查 | 结果 |",
            "|---|---|",
        ]
    )
    for q in bundle.quality:
        detail = f" {q.detail}" if q.detail else ""
        lines.append(f"| {q.name} | {_ok(q.ok)}{detail} |")
    if report.data_quality_note:
        lines.extend(["", f"> 质量备注：{report.data_quality_note}"])

    lines.extend(
        [
            "",
            "## 八、附录：数据溯源",
            "",
            "本报告数据来源：",
        ]
    )
    for src in bundle.data_sources:
        lines.append(f"- {src}")
    lines.append(f"- code_version {bundle.code_version}")
    lines.append(f"- 全部数字可通过 `run_id={report.run_id}` 追溯")
    if report.notable_observations:
        lines.extend(["", "### 观察（仅陈述）", ""])
        for obs in report.notable_observations:
            lines.append(f"- {obs.statement}（{obs.metric}={obs.value}）")
    lines.extend(["", "### Evidence", ""])
    for e in report.evidence:
        lines.append(f"- `{e.evidence_id}` [{e.kind}] {e.ref_id}: {e.excerpt or ''}")
    lines.append("")
    return "\n".join(lines)


def write_daily_report(
    report: DailyReport,
    bundle: ReportBundle,
    path: Path | str,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_daily_report(report, bundle), encoding="utf-8")
    return out
