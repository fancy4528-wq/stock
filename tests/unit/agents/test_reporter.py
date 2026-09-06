"""Unit tests for ReporterAgent and Evidence validation."""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.llm.client import EchoLLMClient
from quantagent.agents.reporter import ReporterAgent, build_deterministic_report
from quantagent.agents.validation import require_evidence
from quantagent.reporting.pipeline import build_synthetic_bundle
from quantagent.shared.errors import EvidenceMissingError, SchemaValidationError


def test_deterministic_report_has_evidence() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    report = build_deterministic_report(bundle)
    assert len(report.evidence) >= 3
    assert "数据显示" in report.market_summary
    assert "买入" not in report.market_summary
    require_evidence(report.evidence, min_count=3)


@pytest.mark.asyncio
async def test_reporter_agent_null_llm() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    agent = ReporterAgent()
    ctx = AgentContext(as_of=bundle.as_of, market="CN", run_id=bundle.run_id)
    report = await agent.run(ctx, bundle)
    assert report.run_id == bundle.run_id
    assert report.as_of == bundle.as_of


@pytest.mark.asyncio
async def test_reporter_agent_echo_llm_invalid_raises() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    agent = ReporterAgent(llm=EchoLLMClient('{"market_summary": "x"}'))
    ctx = AgentContext(as_of=bundle.as_of, market="CN", run_id=bundle.run_id)
    with pytest.raises(SchemaValidationError):
        await agent.run(ctx, bundle)


def test_require_evidence_raises() -> None:
    with pytest.raises(EvidenceMissingError):
        require_evidence([], min_count=1)
