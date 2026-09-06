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
    mode: str = "deterministic"  # deterministic | llm
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CostTracker:
    """In-memory + optional append to docs/cost-log.md."""

    def __init__(self) -> None:
        self.records: list[CostRecord] = []

    def add(self, record: CostRecord) -> None:
        self.records.append(record)

    @property
    def total_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def append_cost_log(self, path: Path | str) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if not out.exists():
            lines.extend(
                [
                    "# LLM cost log",
                    "",
                    "Append-only notes from ReporterAgent / later Agents.",
                    "",
                    "| UTC | run_id | agent | model | mode | prompt | completion | USD |",
                    "|---|---|---|---|---|---:|---:|---:|",
                ]
            )
        for r in self.records:
            lines.append(
                f"| {r.at.isoformat()} | {r.run_id} | {r.agent} | {r.model} | "
                f"{r.mode} | {r.prompt_tokens} | {r.completion_tokens} | {r.cost_usd:.4f} |"
            )
        with out.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
