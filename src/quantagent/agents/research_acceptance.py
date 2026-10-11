"""Gate 2 live-research acceptance summary + append-only log."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from quantagent.agents.llm.metering import CostRecord
from quantagent.agents.orchestrator import OrchestratorResult

DEFAULT_LOG_PATH = Path("docs/research-validation-log.md")

# Gate 2 thresholds (docs/12-roadmap.md §3.3) relevant to a single live run.
GATE2_SCHEMA_PASS_RATE = 0.95
GATE2_PIT_VIOLATIONS = 0
GATE2_DAILY_USD = 1.50
GATE2_RESEARCH_USD = 0.80


class ResearchAcceptanceSummary(BaseModel):
    """One research-live run scored against Gate 2 engineering checks."""

    as_of: date
    run_id: str
    llm_enabled: bool
    aborted: bool = False
    abort_reason: str | None = None
    agents: int = 0
    fatal: int = 0
    warn: int = 0
    evidence_fail: int = 0
    pit_fail: int = 0
    untraceable_total: int = 0
    llm_calls: int = 0
    schema_fails: int = 0
    schema_pass_rate: float = 1.0
    llm_usd: float = 0.0
    degradations: list[str] = Field(default_factory=list)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def mode(self) -> str:
        if not self.llm_enabled:
            return "heuristic"
        if self.llm_calls <= 0:
            return "llm_key_but_no_calls"
        if self.schema_fails > 0 and self.llm_calls > self.schema_fails:
            return "llm_partial"
        if self.schema_fails > 0 and self.llm_calls == 0:
            return "llm_schema_fail"
        return "llm"

    def gate2_rows(self) -> list[tuple[str, str, str, str]]:
        """Return (metric, actual, threshold, result) rows."""
        schema_ok = (
            self.schema_pass_rate >= GATE2_SCHEMA_PASS_RATE
            if self.llm_enabled and (self.llm_calls + self.schema_fails) > 0
            else (self.fatal == 0)
        )
        evidence_ok = self.evidence_fail == 0 and self.agents > 0
        pit_ok = self.pit_fail <= GATE2_PIT_VIOLATIONS
        # docs/06: avg_untraceable < 1; roadmap also cites untraceable rate < 5%.
        avg_untrace = self.untraceable_total / self.agents if self.agents else 0.0
        untrace_ok = avg_untrace < 1.0
        usd_ok = self.llm_usd <= GATE2_RESEARCH_USD
        daily_ok = self.llm_usd <= GATE2_DAILY_USD

        def _r(ok: bool) -> str:
            return "PASS" if ok else "FAIL"

        return [
            (
                "schema_pass_rate",
                f"{self.schema_pass_rate:.1%}",
                f">= {GATE2_SCHEMA_PASS_RATE:.0%}",
                _r(schema_ok),
            ),
            (
                "evidence_coverage",
                "100%" if evidence_ok else f"fail={self.evidence_fail}",
                "100%",
                _r(evidence_ok),
            ),
            (
                "pit_violations",
                str(self.pit_fail),
                str(GATE2_PIT_VIOLATIONS),
                _r(pit_ok),
            ),
            (
                "avg_untraceable_per_agent",
                f"{avg_untrace:.2f}",
                "< 1",
                _r(untrace_ok),
            ),
            (
                "daily_research_usd",
                f"${self.llm_usd:.4f}",
                f"<= ${GATE2_RESEARCH_USD:.2f}",
                _r(usd_ok),
            ),
            (
                "total_usd_vs_daily_cap",
                f"${self.llm_usd:.4f}",
                f"<= ${GATE2_DAILY_USD:.2f}",
                _r(daily_ok),
            ),
            (
                "llm_path",
                self.mode,
                "llm (not heuristic)",
                _r(self.llm_enabled and self.llm_calls > 0),
            ),
        ]

    def overall_pass(self) -> bool:
        if self.aborted or self.agents <= 0:
            return False
        return all(row[3] == "PASS" for row in self.gate2_rows())


def summarize_research_acceptance(
    result: OrchestratorResult,
    *,
    as_of: date,
    run_id: str | None = None,
    llm_enabled: bool | None = None,
    cost_records: list[CostRecord] | None = None,
) -> ResearchAcceptanceSummary:
    enabled = result.llm_enabled if llm_enabled is None else llm_enabled
    records = list(cost_records if cost_records is not None else result.cost_records)
    llm_calls = sum(1 for r in records if r.mode == "llm")
    schema_fails = sum(
        1 for d in result.degradations if d.action == "schema_fail"
    )
    # Cost is recorded before JSON/schema parse; schema_fail degradations mark
    # failed parses. Approximate pass rate = (calls - fails) / calls.
    if enabled and llm_calls > 0:
        schema_pass_rate = max(0.0, (llm_calls - schema_fails) / llm_calls)
    elif enabled and schema_fails > 0:
        schema_pass_rate = 0.0
    else:
        schema_pass_rate = 1.0 if result.validation_fatal_count == 0 else 0.0

    evidence_fail = 0
    pit_fail = 0
    warn = 0
    for v in result.validations:
        if v.has_warn:
            warn += 1
        for c in v.checks:
            if c.passed:
                continue
            if c.name in {"evidence_not_empty", "evidence_ids_exist"} and c.level == "FATAL":
                evidence_fail += 1
            if c.name == "evidence_pit" and c.level == "FATAL":
                pit_fail += 1

    rid = run_id
    if rid is None and result.brief is not None:
        rid = result.brief.run_id
    if rid is None:
        rid = f"{as_of:%Y%m%d}-cn-daily"

    return ResearchAcceptanceSummary(
        as_of=as_of,
        run_id=rid,
        llm_enabled=enabled,
        aborted=result.aborted,
        abort_reason=result.abort_reason,
        agents=len(result.validations),
        fatal=result.validation_fatal_count,
        warn=warn,
        evidence_fail=evidence_fail,
        pit_fail=pit_fail,
        untraceable_total=result.untraceable_figure_count,
        llm_calls=llm_calls,
        schema_fails=schema_fails,
        schema_pass_rate=schema_pass_rate,
        llm_usd=float(result.llm_cost_usd),
        degradations=[f"{d.action}:{d.reason[:80]}" for d in result.degradations[:12]],
    )


def append_research_validation_log(
    summary: ResearchAcceptanceSummary,
    path: Path | str = DEFAULT_LOG_PATH,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if not out.exists():
        lines.extend(
            [
                "# Research validation log (Gate 2)",
                "",
                "Append-only live / smoke research DAG outcomes "
                "(schema / evidence / PIT / untraceable / cost).",
                "",
                "| UTC | run_id | as_of | mode | agents | fatal | warn | "
                "untraceable | llm_calls | schema_fails | schema_pass | "
                "usd | overall |",
                "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
    overall = "PASS" if summary.overall_pass() else "FAIL"
    if summary.aborted:
        overall = "ABORT"
    lines.append(
        f"| {summary.at.isoformat()} | {summary.run_id} | "
        f"{summary.as_of.isoformat()} | {summary.mode} | {summary.agents} | "
        f"{summary.fatal} | {summary.warn} | {summary.untraceable_total} | "
        f"{summary.llm_calls} | {summary.schema_fails} | "
        f"{summary.schema_pass_rate:.1%} | ${summary.llm_usd:.4f} | {overall} |"
    )
    with out.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return out


def format_gate2_table(summary: ResearchAcceptanceSummary) -> str:
    rows = summary.gate2_rows()
    lines = [
        "Gate 2 acceptance (this run):",
        f"  mode={summary.mode} agents={summary.agents} "
        f"fatal={summary.fatal} warn={summary.warn} "
        f"untraceable={summary.untraceable_total} usd=${summary.llm_usd:.4f}",
        f"  {'metric':<28} {'actual':<22} {'threshold':<22} result",
    ]
    for metric, actual, threshold, result in rows:
        lines.append(f"  {metric:<28} {actual:<22} {threshold:<22} {result}")
    lines.append(
        f"  overall={'PASS' if summary.overall_pass() else 'FAIL'}"
        + (f" aborted={summary.abort_reason}" if summary.aborted else "")
    )
    return "\n".join(lines)


def append_cost_log_gate2_section(
    summary: ResearchAcceptanceSummary,
    path: Path | str = Path("docs/cost-log.md"),
) -> None:
    """Append a short Gate 2 research-live section (does not rewrite history)."""
    out = Path(path)
    if not out.exists():
        return
    block = [
        "",
        f"## Gate 2 research-live ({summary.as_of.isoformat()})",
        "",
        f"run_id=`{summary.run_id}` mode=`{summary.mode}` "
        f"overall={'PASS' if summary.overall_pass() else 'FAIL'}",
        "",
        "| Gate 2 | Actual | Threshold | Result |",
        "|---|---|---|---|",
    ]
    for metric, actual, threshold, result in summary.gate2_rows():
        block.append(f"| {metric} | {actual} | {threshold} | {result} |")
    block.append("")
    with out.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block) + "\n")
