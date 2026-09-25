"""Unit tests: notify formatter + log notifier."""

from __future__ import annotations

import asyncio

from quantagent.monitor.types import TriggerHit
from quantagent.notify.base import LogNotifier
from quantagent.notify.formatter import format_alert, format_telegram_text


def test_format_alert_and_telegram() -> None:
    hit = TriggerHit(
        code="PX_STOP_LOSS",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="茅台 浮亏 12%",
        evidence={"holding_return": -0.12},
    )
    alert = format_alert(hit)
    assert alert.trigger_codes == ["PX_STOP_LOSS"]
    assert alert.cost_usd == 0.0
    text = format_telegram_text(alert)
    assert "PX_STOP_LOSS" in text
    assert "L1" in text


def test_log_notifier() -> None:
    hit = TriggerHit(
        code="PX_LIMIT_DOWN",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="跌停",
    )
    alert = format_alert(hit)
    result = asyncio.run(LogNotifier().send(alert))
    assert result.ok
    assert result.channel == "log"
