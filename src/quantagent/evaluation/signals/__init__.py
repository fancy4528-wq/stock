"""Signal cross-section journal and independence check."""

from quantagent.evaluation.signals.correlation import SignalCorrError, check_signal_independence
from quantagent.evaluation.signals.journal import (
    JOURNAL_NAME,
    append_signal_score_day,
    load_signal_score_days,
)
from quantagent.evaluation.signals.report import render_signal_corr_report, write_signal_corr_report
from quantagent.evaluation.signals.types import (
    SignalCorrResult,
    SignalPairCorr,
    SignalScoreDay,
)

__all__ = [
    "JOURNAL_NAME",
    "SignalCorrError",
    "SignalCorrResult",
    "SignalPairCorr",
    "SignalScoreDay",
    "append_signal_score_day",
    "check_signal_independence",
    "load_signal_score_days",
    "render_signal_corr_report",
    "write_signal_corr_report",
]
