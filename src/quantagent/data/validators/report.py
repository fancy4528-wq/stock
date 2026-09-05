"""Validation report contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["FATAL", "ERROR", "WARN", "INFO"]
CheckStatus = Literal["pass", "warn", "fail"]


class RuleResult(BaseModel):
    code: str
    level: Severity
    status: CheckStatus
    detail: str = ""
    affected_count: int = 0
    affected_keys: list[str] = Field(default_factory=list)
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None

    @property
    def failed(self) -> bool:
        return self.status == "fail"


class ValidationReport(BaseModel):
    dataset: str
    check_date: date
    results: list[RuleResult] = Field(default_factory=list)

    @property
    def has_fatal(self) -> bool:
        return any(r.failed and r.level == "FATAL" for r in self.results)

    @property
    def has_error(self) -> bool:
        return any(r.failed and r.level == "ERROR" for r in self.results)

    @property
    def blocking(self) -> bool:
        """FATAL or ERROR — do not load."""
        return self.has_fatal or self.has_error

    def suspect_keys(self) -> set[str]:
        keys: set[str] = set()
        for r in self.results:
            if r.status == "warn" and r.level == "WARN":
                keys.update(r.affected_keys)
        return keys
