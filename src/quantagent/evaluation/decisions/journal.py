"""Append-only journal of daily decision context (``decision_context.jsonl``)."""

from __future__ import annotations

from pathlib import Path

from quantagent.evaluation.decisions.types import DecisionContextDay
from quantagent.evaluation.journal.store import AppendOnlyJournal

JOURNAL_NAME = "decision_context.jsonl"


def decision_context_journal_path(store_dir: Path | str) -> Path:
    return Path(store_dir) / JOURNAL_NAME


def append_decision_context_day(store_dir: Path | str, day: DecisionContextDay) -> bool:
    """Append ``day`` when ``as_of`` is new. Returns True when a row was written."""
    path = decision_context_journal_path(store_dir)
    journal = AppendOnlyJournal(path)
    if journal.has_as_of(day.as_of):
        return False
    journal.append(day)
    return True


def load_decision_context_days(store_dir: Path | str) -> list[DecisionContextDay]:
    path = decision_context_journal_path(store_dir)
    if not path.exists():
        return []
    journal = AppendOnlyJournal(path)
    return [DecisionContextDay.model_validate(row) for row in journal.read_all()]
