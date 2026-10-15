"""Walk-forward training utilities (Gate 3 / docs/07-quant-engine.md §6)."""

from quantagent.quant.training.walk_forward import (
    WalkForwardConfig,
    WalkForwardFold,
    generate_folds,
)

__all__ = [
    "WalkForwardConfig",
    "WalkForwardFold",
    "generate_folds",
]
