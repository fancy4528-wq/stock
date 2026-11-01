"""LLM cost rows from ``docs/cost-log.md`` for one calendar month."""

from __future__ import annotations

import re
from datetime import date, datetime

from quantagent.evaluation.review.types import CostSummary

_RUN_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})")


def _row_date(run_id: str, utc: str) -> date | None:
    """Prefer the trading date embedded in ``run_id``; fall back to the UTC stamp."""
    match = _RUN_DATE.match(run_id.strip())
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    text = utc.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def summarize_cost_log(
    text: str,
    *,
    start: date,
    end: date,
) -> CostSummary:
    """Sum markdown table rows whose run date is inside ``[start, end]``.

    A row is ``| utc | run_id | agent | allocation | ... | usd |``.
    Narrative sections are ignored.
    """
    by_allocation: dict[str, float] = {}
    n_rows = 0
    usd = 0.0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        parts = [part.strip() for part in stripped.strip("|").split("|")]
        if len(parts) < 9 or not parts[0].startswith("20"):
            continue
        row_day = _row_date(parts[1], parts[0])
        if row_day is None or row_day < start or row_day > end:
            continue
        try:
            amount = float(parts[-1].replace("$", "").replace(",", ""))
        except ValueError:
            continue
        allocation = parts[3] or "unknown"
        by_allocation[allocation] = by_allocation.get(allocation, 0.0) + amount
        usd += amount
        n_rows += 1
    return CostSummary(
        n_rows=n_rows,
        usd=usd,
        by_allocation=dict(sorted(by_allocation.items())),
        note="",
    )
