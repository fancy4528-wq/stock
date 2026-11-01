"""Append-only journal of daily signal cross-sections (``signal_scores.jsonl``)."""

from __future__ import annotations

from pathlib import Path

from quantagent.evaluation.journal.store import AppendOnlyJournal
from quantagent.evaluation.signals.types import SignalScoreDay

JOURNAL_NAME = "signal_scores.jsonl"


def signal_score_journal_path(store_dir: Path | str) -> Path:
    return Path(store_dir) / JOURNAL_NAME


def append_signal_score_day(store_dir: Path | str, day: SignalScoreDay) -> bool:
    """Append ``day`` when it has at least one non-empty signal and ``as_of`` is new.

    Returns True when a row was written. An empty day is skipped so a later
    successful run can still record that date. A recorded date is never overwritten.
    """
    signals = {name: scores for name, scores in day.signals.items() if scores}
    if not signals:
        return False
    path = signal_score_journal_path(store_dir)
    journal = AppendOnlyJournal(path)
    if journal.has_as_of(day.as_of):
        return False
    journal.append(day.model_copy(update={"signals": signals}))
    return True


def load_signal_score_days(store_dir: Path | str) -> list[SignalScoreDay]:
    path = signal_score_journal_path(store_dir)
    if not path.exists():
        return []
    journal = AppendOnlyJournal(path)
    return [SignalScoreDay.model_validate(row) for row in journal.read_all()]
