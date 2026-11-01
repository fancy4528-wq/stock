"""Forward Agent score snapshots and evaluation results.

docs/08 §6.3–6.4. Scores are recorded as of the decision date and joined
later to realized returns. Nothing here replays an LLM on past news.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class AgentScorePoint(BaseModel):
    """One symbol scored by the Agent on a decision date."""

    symbol: str
    score: float
    confidence: float = Field(ge=0, le=1)
    horizon: str | None = None


class AgentScoreDay(BaseModel):
    """Append-only cross-section for one ``as_of``."""

    as_of: date
    run_id: str
    agent_name: str = "chief"
    code_version: str = "dev"
    origin: Literal["live", "synthetic"] = "live"
    points: list[AgentScorePoint]


class CalibrationResult(BaseModel):
    """Hit rate by confidence bucket, plus a linear calibration slope."""

    hit_rate_by_bucket: dict[str, float] = Field(default_factory=dict)
    n_by_bucket: dict[str, int] = Field(default_factory=dict)
    slope: float | None = None
    monotonic: bool | None = None
    n: int = 0


class AgentEvalResult(BaseModel):
    """Prediction skill and confidence calibration over a forward window.

    Engineering-quality fields from docs/08 §6.3 (schema pass rate, cost,
    PIT violations) are not filled here; those stay on the research trace.
    """

    agent_name: str
    period: tuple[date, date]
    n_outputs: int
    n_days: int
    n_labeled_5d: int
    n_labeled_20d: int
    n_ic_days_5d: int
    n_ic_days_20d: int

    score_ic_5d: float | None = None
    score_ic_20d: float | None = None
    score_ic_t_stat: float | None = None
    score_ic_20d_t_stat: float | None = None
    ranking_ic: float | None = None

    confidence_calibration: dict[str, float] = Field(default_factory=dict)
    calibration_n: dict[str, int] = Field(default_factory=dict)
    calibration_slope: float | None = None
    calibration_monotonic: bool | None = None

    interpretation: str = ""
