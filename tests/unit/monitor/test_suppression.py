"""Unit tests: suppression policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quantagent.monitor.suppression import (
    QuietWindow,
    SuppressionPolicy,
    SuppressionState,
    filter_hits,
    in_quiet_hours,
    load_suppression_policy,
)
from quantagent.monitor.types import TriggerHit


def _hit(
    code: str = "PX_STOP_LOSS",
    symbol: str = "600519.SH",
    severity: str = "critical",
    cool: float = 24.0,
) -> TriggerHit:
    return TriggerHit(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        symbol=symbol,
        title=code,
        message="test",
        cooldown_hours=cool,
    )


def test_load_suppression_policy() -> None:
    pol = load_suppression_policy()
    assert pol.max_alerts_per_day == 10


def test_cooldown_suppresses() -> None:
    now = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    state = SuppressionState()
    state.record(_hit(), when=now - timedelta(hours=1))
    d = filter_hits([_hit()], state, SuppressionPolicy(), now=now)
    assert not d.allowed
    assert d.suppressed[0][1].startswith("cooldown")


def test_daily_cap() -> None:
    now = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    pol = SuppressionPolicy(max_alerts_per_day=2, quiet_hours=[])
    state = SuppressionState()
    hits = [
        _hit(code=f"PX_{i}", symbol=f"S{i}.SH", severity="high") for i in range(5)
    ]
    d = filter_hits(hits, state, pol, now=now)
    assert len(d.allowed) == 2
    assert len(d.suppressed) == 3


def test_quiet_hours_critical_bypass() -> None:
    # 23:00 is inside 22:00-08:00
    now = datetime(2026, 9, 20, 23, 0, tzinfo=UTC)
    pol = SuppressionPolicy(
        quiet_hours=[QuietWindow(start="22:00", end="08:00")],
        critical_bypasses_quiet=True,
    )
    assert in_quiet_hours(now, pol.quiet_hours)
    d = filter_hits(
        [_hit(severity="critical"), _hit(code="PX_VOL", severity="high", symbol="X.SH")],
        SuppressionState(),
        pol,
        now=now,
    )
    assert len(d.allowed) == 1
    assert d.allowed[0].severity == "critical"
    assert d.suppressed[0][1] == "quiet_hours"


def test_state_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sup.json"
    state = SuppressionState()
    state.record(_hit(), when=datetime(2026, 9, 20, tzinfo=UTC))
    state.save(path)
    loaded = SuppressionState.load(path)
    assert len(loaded.fires) == 1
