"""ReporterAgent Pydantic validation success/fail tracking (Gate 1 observability)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ValidationRecord(BaseModel):
    run_id: str
    as_of: date
    agent: str = "reporter"
    mode: str = "deterministic"  # deterministic | llm
    ok: bool
    error_type: str | None = None
    detail: str | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ValidationTracker:
    """In-memory + append-only markdown log for schema validation outcomes."""

    def __init__(self) -> None:
        self.records: list[ValidationRecord] = []

    def add(self, record: ValidationRecord) -> None:
        self.records.append(record)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.records if not r.ok)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.records if r.ok)

    def fail_rate(self) -> float:
        n = len(self.records)
        if n == 0:
            return 0.0
        return self.fail_count / n

    def append_validation_log(self, path: Path | str) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if not out.exists():
            lines.extend(
                [
                    "# Reporter validation log",
                    "",
                    "Append-only schema validation outcomes (Gate 1 fail-rate evidence).",
                    "",
                    "| UTC | run_id | as_of | agent | mode | ok | error_type | detail |",
                    "|---|---|---|---|---|---|---|---|",
                ]
            )
        for r in self.records:
            detail = (r.detail or "").replace("|", "/").replace("\n", " ")[:120]
            lines.append(
                f"| {r.at.isoformat()} | {r.run_id} | {r.as_of.isoformat()} | "
                f"{r.agent} | {r.mode} | {str(r.ok).lower()} | "
                f"{r.error_type or ''} | {detail} |"
            )
        with out.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def summarize_validation_log(path: Path | str) -> dict[str, float | int]:
    """Parse markdown table rows and return fail-rate stats."""
    out = Path(path)
    if not out.is_file():
        return {"n": 0, "n_ok": 0, "n_fail": 0, "fail_rate": 0.0}
    n_ok = 0
    n_fail = 0
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| UTC") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 6:
            continue
        ok_cell = cols[5].lower()
        if ok_cell == "true":
            n_ok += 1
        elif ok_cell == "false":
            n_fail += 1
    n = n_ok + n_fail
    return {
        "n": n,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "fail_rate": (n_fail / n) if n else 0.0,
    }
