"""Format TriggerHit → AlertMessage for notifiers."""

from __future__ import annotations

from datetime import UTC, datetime

from quantagent.monitor.types import TriggerHit
from quantagent.notify.base import AlertMessage

_SEV_ICON = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "info": "ℹ️",
}


def alert_id_for(hit: TriggerHit, *, when: datetime | None = None) -> str:
    ts = when or datetime.now(UTC)
    day = ts.astimezone(UTC).strftime("%Y%m%d")
    return f"{day}-{hit.code}-{hit.symbol}-0"


def format_alert(hit: TriggerHit, *, when: datetime | None = None) -> AlertMessage:
    icon = _SEV_ICON.get(hit.severity, "")
    title = f"{icon} {hit.message}".strip()[:60]
    state_parts = []
    for k in (
        "holding_return",
        "weight",
        "drawdown",
        "daily_pnl_pct",
        "cash_ratio",
        "last",
        "announce_type",
        "title",
    ):
        if k in hit.evidence and hit.evidence[k] is not None:
            state_parts.append(f"{k}={hit.evidence[k]}")
    return AlertMessage(
        alert_id=alert_id_for(hit, when=when),
        created_at=when or datetime.now(UTC),
        severity=hit.severity,
        title=title,
        trigger_reason=f"触发: {hit.code}",
        current_state="; ".join(state_parts) if state_parts else hit.message,
        suggestion="提醒仅供参考，不自动下单。请自行确认后操作。",
        symbols=[hit.symbol],
        trigger_codes=[hit.code],
        analysis_level=hit.analysis_level,
        cost_usd=hit.cost_usd,
        evidence=dict(hit.evidence),
    )


def format_telegram_text(alert: AlertMessage) -> str:
    lines = [
        f"<b>{alert.title}</b>",
        alert.trigger_reason,
    ]
    if alert.current_state:
        lines.append(f"当前: {alert.current_state}")
    if alert.suggestion:
        lines.append(f"建议: {alert.suggestion}")
    lines.append(
        f"分析级别: {alert.analysis_level}  成本: ${alert.cost_usd:.4f}"
    )
    return "\n".join(lines)
