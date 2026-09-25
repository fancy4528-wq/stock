"""Notifier adapter protocol (P2a)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class AlertMessage(BaseModel):
    """Channel-agnostic alert payload (pre-DB alert table)."""

    alert_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    severity: Literal["critical", "high", "medium", "info"]
    title: str
    trigger_reason: str
    current_state: str = ""
    suggestion: str | None = None
    symbols: list[str] = Field(default_factory=list)
    trigger_codes: list[str] = Field(default_factory=list)
    analysis_level: Literal["L1", "L2", "L3"] = "L1"
    cost_usd: float = 0.0
    evidence: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    channel: str
    detail: str = ""
    message_id: str | None = None


class NotifierAdapter(ABC):
    @abstractmethod
    async def send(self, alert: AlertMessage) -> DeliveryResult: ...

    def supports_interactive(self) -> bool:
        return False


class LogNotifier(NotifierAdapter):
    """Dev fallback: print to stdout, always succeeds."""

    async def send(self, alert: AlertMessage) -> DeliveryResult:
        print(
            f"[notify/log] [{alert.severity}] {alert.title}\n"
            f"  {alert.trigger_reason}\n"
            f"  codes={alert.trigger_codes} symbols={alert.symbols} "
            f"cost=${alert.cost_usd:.4f} level={alert.analysis_level}"
        )
        return DeliveryResult(ok=True, channel="log", detail="printed")
