"""Unit conversion helpers for Normalizers.

Each conversion documents source unit → canonical unit and must be covered by tests.
"""

from __future__ import annotations


def lots_to_shares(volume_lots: float | int) -> int:
    """East Money / akshare volume is in 手 (100 shares). Canonical: 股."""
    return int(round(float(volume_lots) * 100))


def percent_to_ratio(value: float | int) -> float:
    """Convert percent (15.0 meaning 15%) to decimal ratio (0.15)."""
    return float(value) / 100.0
