"""Shared data-layer contracts (avoid circular imports)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawBatch(BaseModel):
    """Result of one collect call, pointing at an archived Parquet file."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    batch_id: int
    source: str
    dataset: str
    target_date: date | None
    raw_path: Path
    row_count: int
    collected_at: datetime
    meta: dict[str, Any] = Field(default_factory=dict)
