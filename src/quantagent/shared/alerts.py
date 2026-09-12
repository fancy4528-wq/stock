"""Minimal alert channel for data-quality FATAL events."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_FATAL_LOG = Path("data/alerts/fatal.log")


def notify_data_quality_fatal(code: str, detail: str, *, run_id: str | None = None) -> None:
    """Write FATAL alert to stderr and append to ``data/alerts/fatal.log``."""
    ts = datetime.now(UTC).isoformat()
    msg = f"[{ts}] FATAL {code}: {detail}"
    if run_id:
        msg = f"{msg} run_id={run_id}"
    print(msg, file=sys.stderr)
    _FATAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _FATAL_LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
