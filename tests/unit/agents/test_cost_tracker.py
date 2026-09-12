"""CostTracker append-only log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from quantagent.agents.llm.metering import CostRecord, CostTracker


def test_append_cost_log_writes_row(tmp_path: Path) -> None:
    log_path = tmp_path / "cost-log.md"
    tracker = CostTracker()
    tracker.add(
        CostRecord(
            run_id="20260901-cn-daily",
            agent="reporter",
            model="deterministic",
            mode="deterministic",
            cost_usd=0.0,
            at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )
    )
    tracker.append_cost_log(log_path)
    text = log_path.read_text(encoding="utf-8")
    assert "20260901-cn-daily" in text
    assert "deterministic" in text
    assert "| 0.0000 |" in text or "| 0.0 |" in text
