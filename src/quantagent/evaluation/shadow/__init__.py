"""Shadow Portfolio (P1 + P2 shadow_agent)."""

from quantagent.evaluation.shadow.agent_signals import scores_from_brief, scores_from_stock_views
from quantagent.evaluation.shadow.engine import ShadowEngine
from quantagent.evaluation.shadow.stats import summarize_unfilled
from quantagent.evaluation.shadow.types import ShadowConfig, ShadowDayRecord

__all__ = [
    "ShadowConfig",
    "ShadowDayRecord",
    "ShadowEngine",
    "scores_from_brief",
    "scores_from_stock_views",
    "summarize_unfilled",
]
