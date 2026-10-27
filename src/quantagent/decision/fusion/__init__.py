"""Signal Fusion (P4): multi-signal → single score."""

from quantagent.decision.fusion.engine import SignalFusion
from quantagent.decision.fusion.types import DEFAULT_WEIGHTS, FusionConfig, FusedScore

__all__ = [
    "DEFAULT_WEIGHTS",
    "FusionConfig",
    "FusedScore",
    "SignalFusion",
]
