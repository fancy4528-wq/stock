"""Shared helpers for deterministic research Agents."""

from __future__ import annotations

from datetime import date
from typing import Literal

from quantagent.agents.base import Evidence
from quantagent.agents.schemas.views import ArgumentPoint, DimScore, RiskNote


def dim(score: float, note: str, refs: list[str] | None = None) -> DimScore:
    return DimScore(score=_clamp01(score), note=note[:150], evidence_refs=list(refs or []))


def point(
    text: str,
    strength: Literal["weak", "moderate", "strong"],
    refs: list[str],
) -> ArgumentPoint:
    return ArgumentPoint(point=text[:200], strength=strength, evidence_refs=refs)


def risk(
    text: str,
    *,
    severity: Literal["low", "medium", "high"] = "medium",
    probability: Literal["low", "medium", "high"] = "medium",
) -> RiskNote:
    return RiskNote(
        risk=text,
        severity=severity,
        probability=probability,
        monitorable=True,
    )


def evidence(
    evidence_id: str,
    *,
    kind: str,
    ref_id: str,
    excerpt: str,
    as_of: date,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        ref_id=ref_id,
        excerpt=excerpt[:400],
        as_of=as_of,
    )


def score_from_return(ret: float, *, center: float = 0.5, scale: float = 5.0) -> float:
    """Map a return to [0, 1] around ``center``."""
    return _clamp01(center + ret * scale)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
