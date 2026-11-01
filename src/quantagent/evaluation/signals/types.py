"""Signal cross-sections and independence results (docs/08 §7.3)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# Fusion slots in ``FusionConfig`` / docs/09. ``factor`` is shadow_factor only.
FUSION_SLOTS: tuple[str, ...] = ("quant", "sector", "stock", "macro_fit", "news")
SIGNAL_ORDER: tuple[str, ...] = ("factor", *FUSION_SLOTS)

# docs/08 §7.3: pairs above this should be merged, or equal weight double-counts them.
MERGE_ABS_CORR: float = 0.7
# Same bar as Agent IC: do not change Fusion weights on a shorter window.
MIN_DAYS_FOR_ACTION: int = 20
# A 3-name Spearman is almost noise. Pairs need a real cross-section.
MIN_NAMES: int = 5


class SignalScoreDay(BaseModel):
    """One day's raw scores, the inputs Fusion and the shadows actually used.

    ``stock`` is the Agent score map. ``factor`` is the single-factor shadow
    (``mom_20d``), which is not one of the five Fusion slots. Synthetic daily
    reports share this file and are excluded from the correlation unless asked.
    """

    as_of: date
    run_id: str
    origin: Literal["live", "synthetic"] = "live"
    code_version: str = "dev"
    signals: dict[str, dict[str, float]] = Field(default_factory=dict)


class SignalPairCorr(BaseModel):
    """Mean daily Spearman between two signals on their overlapping names."""

    left: str
    right: str
    corr: float
    n_days: int
    mean_names: float
    flag: Literal["ok", "merge", "tracking"]


class SignalICStat(BaseModel):
    """Standalone IC of one recorded signal. Empty until a price panel is joined."""

    signal: str
    horizon: Literal["5d", "20d"]
    ic_mean: float | None = None
    ic_t_stat: float | None = None
    n_days: int = 0


class SignalCorrResult(BaseModel):
    """Independence check. This object never edits Fusion weights."""

    period: tuple[date, date] | None = None
    n_days: int = 0
    signals: list[str] = Field(default_factory=list)
    missing_fusion_slots: list[str] = Field(default_factory=list)
    pairs: list[SignalPairCorr] = Field(default_factory=list)
    ics: list[SignalICStat] = Field(default_factory=list)
    weights_changed: bool = False
    interpretation: str = ""
