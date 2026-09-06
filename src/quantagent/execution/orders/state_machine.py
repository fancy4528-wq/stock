"""Order lifecycle state machine."""

from __future__ import annotations

from typing import Literal

from quantagent.shared.errors import QuantAgentError

OrderStatus = Literal[
    "proposed",
    "risk_approved",
    "risk_rejected",
    "submitting",
    "submitted",
    "unknown",
    "partial",
    "filled",
    "cancelled",
    "expired",
    "rejected",
    "duplicate",
]

VALID_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"risk_approved", "risk_rejected"},
    "risk_approved": {"submitting"},
    "submitting": {"submitted", "rejected", "unknown", "duplicate"},
    "unknown": {"submitted", "partial", "filled", "rejected", "cancelled"},
    "submitted": {"partial", "filled", "cancelled", "expired", "rejected"},
    "partial": {"filled", "cancelled", "expired"},
    "filled": set(),
    "cancelled": set(),
    "expired": set(),
    "rejected": set(),
    "risk_rejected": set(),
    "duplicate": set(),
}


class InvalidTransition(QuantAgentError):
    """Illegal order status transition."""


def assert_transition(current: str, new_status: str) -> None:
    allowed = VALID_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidTransition(f"unknown status: {current}")
    if new_status not in allowed:
        raise InvalidTransition(f"{current} → {new_status}")


def transition(current: str, new_status: str) -> str:
    assert_transition(current, new_status)
    return new_status
