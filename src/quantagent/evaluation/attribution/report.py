"""Markdown section for docs/08 §7 attribution."""

from __future__ import annotations

from quantagent.evaluation.attribution.types import AttributionResult, ReturnDecomposition


def _pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:+.2%}"


def _num(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def render_return_decomposition(decomp: ReturnDecomposition) -> str:
    """Markdown table for §7.1."""
    lines = [
        "### 收益分解（docs/08 §7.1）",
        "",
        "| 分项 | 贡献 |",
        "|---|---:|",
        f"| 总收益 | {_pct(decomp.total_return)} |",
        f"| 市场（β×基准） | {_pct(decomp.market)} |",
        f"| 板块配置 | {_pct(decomp.sector_allocation)} |",
        f"| 个股选择 | {_pct(decomp.stock_selection)} |",
        f"| 择时 | {_pct(decomp.timing)} |",
        f"| 交易成本 | {_pct(decomp.cost)} |",
        f"| Residual | {_pct(decomp.residual)} |",
        "",
        f"- β = {_num(decomp.beta)}；基准总收益 = {_pct(decomp.benchmark_return)}；"
        f"有效交易日 = {decomp.n_days}",
    ]
    if decomp.note:
        lines.append(f"- {decomp.note}")
    return "\n".join(lines)


def render_attribution_section(result: AttributionResult) -> str:
    """Full §8-style attribution block for the portfolio backtest report."""
    parts = [
        "## 8. 归因分析",
        "",
        render_return_decomposition(result.returns),
        "",
        "### 信号贡献（docs/08 §7.2）",
        "",
    ]
    if not result.signals:
        parts.append(result.signal_note or "（未提供单信号组合收益）")
    else:
        parts.extend(
            [
                "| 信号 | 组合收益 | vs 基准 | vs fused |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in result.signals:
            parts.append(
                f"| `{row.signal}` | {_pct(row.portfolio_return)} | "
                f"{_pct(row.vs_baseline)} | {_pct(row.vs_fused)} |"
            )
        if result.signal_note:
            parts.extend(["", f"- {result.signal_note}"])
    parts.append("")
    return "\n".join(parts)
