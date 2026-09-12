"""Unit tests for FATAL alert channel."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantagent.shared import alerts


def test_notify_appends_fatal_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "fatal.log"
    monkeypatch.setattr(alerts, "_FATAL_LOG", log_path)
    alerts.notify_data_quality_fatal(
        "PIT_001", "announced_at > ingested_at", run_id="20260912-cn-daily"
    )
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "FATAL PIT_001" in text
    assert "run_id=20260912-cn-daily" in text
    alerts.notify_data_quality_fatal("PIT_003", "overlap")
    assert log_path.read_text(encoding="utf-8").count("FATAL") == 2
