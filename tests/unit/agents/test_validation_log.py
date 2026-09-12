"""Unit tests for Reporter validation tracker / fail-rate summary."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.llm.client import EchoLLMClient
from quantagent.agents.reporter import ReporterAgent
from quantagent.agents.reporter.validation_log import (
    ValidationRecord,
    ValidationTracker,
    summarize_validation_log,
)
from quantagent.reporting.pipeline import build_synthetic_bundle
from quantagent.shared.errors import SchemaValidationError


def test_validation_tracker_fail_rate(tmp_path: Path) -> None:
    tracker = ValidationTracker()
    tracker.add(
        ValidationRecord(
            run_id="r1",
            as_of=date(2026, 9, 1),
            mode="deterministic",
            ok=True,
        )
    )
    tracker.add(
        ValidationRecord(
            run_id="r2",
            as_of=date(2026, 9, 2),
            mode="llm",
            ok=False,
            error_type="SchemaValidationError",
            detail="bad",
        )
    )
    assert tracker.fail_rate() == pytest.approx(0.5)
    path = tmp_path / "reporter-validation-log.md"
    tracker.append_validation_log(path)
    stats = summarize_validation_log(path)
    assert stats["n"] == 2
    assert stats["n_fail"] == 1
    assert stats["fail_rate"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_reporter_logs_llm_validation_failure() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    tracker = ValidationTracker()
    agent = ReporterAgent(
        llm=EchoLLMClient('{"market_summary": "x"}'),
        validation_tracker=tracker,
    )
    ctx = AgentContext(as_of=bundle.as_of, market="CN", run_id=bundle.run_id)
    with pytest.raises(SchemaValidationError):
        await agent.run(ctx, bundle)
    assert tracker.fail_count == 1
    assert tracker.records[0].mode == "llm"
    assert tracker.records[0].ok is False


@pytest.mark.asyncio
async def test_reporter_logs_deterministic_pass() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    tracker = ValidationTracker()
    agent = ReporterAgent(validation_tracker=tracker)
    ctx = AgentContext(as_of=bundle.as_of, market="CN", run_id=bundle.run_id)
    await agent.run(ctx, bundle)
    assert tracker.pass_count == 1
    assert tracker.fail_rate() == 0.0
