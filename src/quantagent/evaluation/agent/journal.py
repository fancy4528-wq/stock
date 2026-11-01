"""Append-only journal of daily Agent scores (``agent_scores.jsonl``)."""

from __future__ import annotations

from pathlib import Path

from quantagent.evaluation.agent.types import AgentScoreDay
from quantagent.evaluation.journal.store import AppendOnlyJournal

JOURNAL_NAME = "agent_scores.jsonl"


def agent_score_journal_path(store_dir: Path | str) -> Path:
    return Path(store_dir) / JOURNAL_NAME


def append_agent_score_day(store_dir: Path | str, day: AgentScoreDay) -> bool:
    """Append ``day`` when it has points and ``as_of`` is new.

    Returns True when a row was written. An empty cross-section is skipped so
    a later successful research run can still record that date. A recorded
    date is never overwritten.
    """
    if not day.points:
        return False
    path = agent_score_journal_path(store_dir)
    journal = AppendOnlyJournal(path)
    if journal.has_as_of(day.as_of):
        return False
    journal.append(day)
    return True


def load_agent_score_days(store_dir: Path | str) -> list[AgentScoreDay]:
    path = agent_score_journal_path(store_dir)
    if not path.exists():
        return []
    journal = AppendOnlyJournal(path)
    return [AgentScoreDay.model_validate(row) for row in journal.read_all()]
