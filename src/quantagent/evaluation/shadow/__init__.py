"""Shadow Portfolio (P1 factor + P2 agent + P3 quant)."""

from quantagent.evaluation.shadow.agent_signals import scores_from_brief, scores_from_stock_views
from quantagent.evaluation.shadow.engine import ShadowEngine
from quantagent.evaluation.shadow.quant_signals import (
    CSI300_L2_IC_MEANS_5Y,
    l2_equal_scores_as_of,
    load_l2_equal_scores,
)
from quantagent.evaluation.shadow.stats import summarize_unfilled
from quantagent.evaluation.shadow.types import ShadowConfig, ShadowDayRecord

__all__ = [
    "CSI300_L2_IC_MEANS_5Y",
    "ShadowConfig",
    "ShadowDayRecord",
    "ShadowEngine",
    "l2_equal_scores_as_of",
    "load_l2_equal_scores",
    "scores_from_brief",
    "scores_from_stock_views",
    "summarize_unfilled",
]
