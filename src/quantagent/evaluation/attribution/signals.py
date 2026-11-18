"""Signal contribution attribution (docs/08 §7.2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from quantagent.evaluation.attribution.types import SignalContribution
from quantagent.evaluation.shadow.types import ShadowDayRecord, ShadowPortfolioId

# Shadow portfolios that stand in for "只用该信号的组合".
_SHADOW_SIGNAL_LABEL: dict[ShadowPortfolioId, str] = {
    "shadow_baseline": "baseline",
    "shadow_factor": "factor",
    "shadow_quant": "quant",
    "shadow_agent": "stock",
    "shadow_fused": "fused",
    "shadow_fused_norisk": "fused_norisk",
}


def window_return(records: Sequence[ShadowDayRecord]) -> float | None:
    """Cumulative return over an ordered shadow window (last ret_cum, or NAV)."""
    if not records:
        return None
    ordered = sorted(records, key=lambda r: r.as_of)
    first, last = ordered[0], ordered[-1]
    if first.nav and first.nav > 0 and last.nav is not None:
        # Prefer NAV so mid-window appends stay consistent.
        if len(ordered) >= 2:
            return float(last.nav) / float(first.nav) - 1.0
    return float(last.ret_cum) if last.ret_cum is not None else None


def signal_returns_from_shadows(
    days: Sequence[ShadowDayRecord],
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, float]:
    """Map signal label → total return from shadow journals in ``[start, end]``."""
    by_port: dict[str, list[ShadowDayRecord]] = {}
    for day in days:
        if start is not None and day.as_of < start:
            continue
        if end is not None and day.as_of > end:
            continue
        label = _SHADOW_SIGNAL_LABEL.get(day.portfolio, day.portfolio)
        by_port.setdefault(label, []).append(day)

    out: dict[str, float] = {}
    for label, rows in by_port.items():
        ret = window_return(rows)
        if ret is not None:
            out[label] = ret
    return out


def attribute_by_signal(
    *,
    fused_return: float | None = None,
    baseline_return: float | None = None,
    signal_returns: Mapping[str, float],
) -> tuple[list[SignalContribution], str]:
    """Compare each single-signal portfolio to fused / baseline (docs/08 §7.2).

    Contributions are descriptive (standalone portfolio returns), not an
    additive split of fused P&L. Empty ``signal_returns`` yields a tracking note.
    """
    if not signal_returns:
        return [], "无单信号组合收益，信号贡献未算。不改 Fusion 权重。"

    rows: list[SignalContribution] = []
    for name in sorted(signal_returns):
        ret = float(signal_returns[name])
        vs_base = None if baseline_return is None else ret - float(baseline_return)
        vs_fused = None if fused_return is None else ret - float(fused_return)
        rows.append(
            SignalContribution(
                signal=name,
                portfolio_return=ret,
                vs_baseline=vs_base,
                vs_fused=vs_fused,
            )
        )

    parts = [
        f"共 {len(rows)} 个单信号/对照组合；方法=只用该信号的组合收益 vs 实际/基准。"
    ]
    if fused_return is not None:
        parts.append(f"fused={fused_return:+.2%}")
    if baseline_return is not None:
        parts.append(f"baseline={baseline_return:+.2%}")
    parts.append("不改 Fusion 权重。")
    return rows, " ".join(parts)
