"""Agent output validation helpers."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from quantagent.agents.base import Evidence
from quantagent.shared.errors import EvidenceMissingError, SchemaValidationError


def require_evidence(evidence: Sequence[Evidence], *, min_count: int = 1) -> None:
    if len(evidence) < min_count:
        raise EvidenceMissingError(
            f"expected at least {min_count} evidence items, got {len(evidence)}"
        )


def validate_model(model: BaseModel) -> BaseModel:
    """Re-validate a model instance (catches hand-built invalid objects)."""
    try:
        return model.__class__.model_validate(model.model_dump())
    except Exception as exc:  # noqa: BLE001 — wrap as SchemaValidationError
        raise SchemaValidationError(str(exc)) from exc
