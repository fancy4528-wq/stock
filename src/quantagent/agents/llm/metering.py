"""Token / USD cost tracking for Agent calls."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class CostRecord(BaseModel):
    run_id: str
    agent: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    mode: str = "deterministic"  # deterministic | llm | budget_skip | budget_degrade
    allocation: str = "daily_research"
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


_COST_LOG_HEADER = (
    "| UTC | run_id | agent | allocation | model | mode | prompt | completion | USD |"
)
_COST_LOG_SEP = "|---|---|---|---|---|---|---:|---:|---:|"


class CostTracker:
    """In-memory + optional append to docs/cost-log.md."""

    def __init__(self) -> None:
        self.records: list[CostRecord] = []
        self._flushed = 0

    def add(self, record: CostRecord) -> None:
        self.records.append(record)

    @property
    def total_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def total_usd_for(self, allocation: str) -> float:
        return sum(r.cost_usd for r in self.records if r.allocation == allocation)

    def append_cost_log(self, path: Path | str) -> None:
        pending = self.records[self._flushed :]
        if not pending:
            return
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if not out.exists():
            lines.extend(
                [
                    "# LLM cost log",
                    "",
                    "Append-only notes from ReporterAgent / later Agents "
                    "(allocation = ADR-0010 budget pool).",
                    "",
                    _COST_LOG_HEADER,
                    _COST_LOG_SEP,
                ]
            )
        else:
            existing = out.read_text(encoding="utf-8")
            if "| allocation |" not in existing:
                lines.extend(
                    [
                        "",
                        "<!-- schema v2: allocation column -->",
                        _COST_LOG_HEADER,
                        _COST_LOG_SEP,
                    ]
                )
        for r in pending:
            lines.append(
                f"| {r.at.isoformat()} | {r.run_id} | {r.agent} | {r.allocation} | "
                f"{r.model} | {r.mode} | {r.prompt_tokens} | {r.completion_tokens} | "
                f"{r.cost_usd:.4f} |"
            )
        with out.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        self._flushed = len(self.records)
