"""Shadow Portfolio (P1–P4: factor / agent / quant / fused)."""

from quantagent.evaluation.shadow.agent_signals import scores_from_brief, scores_from_stock_views
from quantagent.evaluation.shadow.engine import ShadowEngine
from quantagent.evaluation.shadow.fusion_signals import fuse_quant_agent_scores
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
    "fuse_quant_agent_scores",
    "l2_equal_scores_as_of",
    "load_l2_equal_scores",
    "scores_from_brief",
    "scores_from_stock_views",
    "summarize_unfilled",
]
