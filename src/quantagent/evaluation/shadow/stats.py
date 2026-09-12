"""Shadow portfolio reject / unfilled order statistics."""

from __future__ import annotations

from quantagent.evaluation.shadow.types import ShadowDayRecord


def summarize_unfilled(records: list[ShadowDayRecord]) -> dict[str, int]:
    """Count unfilled order reasons across shadow day records."""
    counts: dict[str, int] = {}
    for rec in records:
        for item in rec.unfilled:
            reason = str(item.get("reason", "unknown"))
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
