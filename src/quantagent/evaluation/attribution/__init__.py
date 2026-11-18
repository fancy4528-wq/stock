"""Performance attribution (docs/08 §7)."""

from quantagent.evaluation.attribution.pipeline import attribute_portfolio
from quantagent.evaluation.attribution.report import (
    render_attribution_section,
    render_return_decomposition,
)
from quantagent.evaluation.attribution.returns import (
    align_benchmark_returns,
    daily_returns_from_equity,
    daily_stock_returns_from_bars,
    decompose_returns,
)
from quantagent.evaluation.attribution.signals import (
    attribute_by_signal,
    signal_returns_from_shadows,
    window_return,
)
from quantagent.evaluation.attribution.types import (
    AttributionResult,
    ReturnDecomposition,
    SignalContribution,
)

__all__ = [
    "AttributionResult",
    "ReturnDecomposition",
    "SignalContribution",
    "align_benchmark_returns",
    "attribute_by_signal",
    "attribute_portfolio",
    "daily_returns_from_equity",
    "daily_stock_returns_from_bars",
    "decompose_returns",
    "render_attribution_section",
    "render_return_decomposition",
    "signal_returns_from_shadows",
    "window_return",
]
