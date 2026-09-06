"""Factor evaluation: IC, quantile tests, decay, reports (P1 W6)."""

from quantagent.quant.evaluation.decay import ic_decay
from quantagent.quant.evaluation.ic import (
    cross_sectional_spearman,
    daily_ic_series,
    summarize_ic,
)
from quantagent.quant.evaluation.quantile import quantile_analysis
from quantagent.quant.evaluation.report import (
    render_factor_report,
    write_factor_report,
    write_factor_reports,
)
from quantagent.quant.evaluation.runner import (
    ADMISSION,
    evaluate_factor,
    evaluate_factors,
    passes_admission,
    synthetic_eval_panel,
)
from quantagent.quant.evaluation.types import FactorTestResult, ICSummary, QuantileSummary

__all__ = [
    "ADMISSION",
    "FactorTestResult",
    "ICSummary",
    "QuantileSummary",
    "cross_sectional_spearman",
    "daily_ic_series",
    "evaluate_factor",
    "evaluate_factors",
    "ic_decay",
    "passes_admission",
    "quantile_analysis",
    "render_factor_report",
    "summarize_ic",
    "synthetic_eval_panel",
    "write_factor_report",
    "write_factor_reports",
]
