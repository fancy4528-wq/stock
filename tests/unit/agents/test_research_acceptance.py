"""Gate 2 research acceptance summarizer."""

from __future__ import annotations

from datetime import date

from quantagent.agents.llm.budget import DegradationNote
from quantagent.agents.llm.metering import CostRecord
from quantagent.agents.orchestrator import OrchestratorResult
from quantagent.agents.research_acceptance import (
    summarize_research_acceptance,
)
from quantagent.agents.validation import CheckResult, ValidationResult


def test_summarize_heuristic_pass() -> None:
    result = OrchestratorResult(
        llm_enabled=False,
        validations=[
            ValidationResult(
                agent_name="macro",
                checks=[
                    CheckResult(name="evidence_not_empty", passed=True, level="FATAL"),
                    CheckResult(name="evidence_pit", passed=True, level="FATAL"),
                ],
            )
        ],
    )
    summary = summarize_research_acceptance(result, as_of=date(2026, 9, 30))
    assert summary.mode == "heuristic"
    assert summary.schema_pass_rate == 1.0
    assert summary.agents == 1
    # llm_path row fails on heuristic — overall should fail Gate 2 live accept
    assert not summary.overall_pass()


def test_summarize_llm_schema_rate() -> None:
    result = OrchestratorResult(
        llm_enabled=True,
        llm_cost_usd=0.12,
        cost_records=[
            CostRecord(
                run_id="r1",
                agent="macro",
                model="deepseek-chat",
                mode="llm",
                cost_usd=0.06,
            ),
            CostRecord(
                run_id="r1",
                agent="chief",
                model="deepseek-chat",
                mode="llm",
                cost_usd=0.06,
            ),
        ],
        degradations=[
            DegradationNote(
                allocation="daily_research",
                action="schema_fail",
                reason="bad json",
                impact="macro",
            )
        ],
        validations=[
            ValidationResult(
                agent_name="macro",
                checks=[
                    CheckResult(name="evidence_not_empty", passed=True, level="FATAL"),
                    CheckResult(name="evidence_pit", passed=True, level="FATAL"),
                ],
            ),
            ValidationResult(
                agent_name="chief",
                checks=[
                    CheckResult(name="evidence_not_empty", passed=True, level="FATAL"),
                    CheckResult(name="evidence_pit", passed=True, level="FATAL"),
                ],
            ),
        ],
    )
    summary = summarize_research_acceptance(result, as_of=date(2026, 9, 30), run_id="r1")
    assert summary.llm_calls == 2
    assert summary.schema_fails == 1
    assert summary.schema_pass_rate == 0.5
    assert summary.mode == "llm_partial"
