"""Load structured events for a report ``as_of`` session (PIT by visible_at)."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy.engine import Engine

from quantagent.agents.tools.market import EventRow
from quantagent.core.repository.pit import PITRepository


def load_events_for_as_of(
    as_of: date,
    *,
    limit: int = 12,
    engine: Engine | None = None,
    universe_symbols: list[str] | None = None,
    repo: PITRepository | None = None,
) -> list[EventRow]:
    """Return events with ``visible_at`` on ``as_of`` (Shanghai calendar day).

    Prefers events linked to ``universe_symbols`` when provided, then by impact.
    Soft-fails to ``[]`` if ``event`` / ``news`` tables are missing.
    """
    pit = repo or PITRepository(engine=engine)
    uni = set(universe_symbols or [])
    try:
        rows = pit.fetch_events_on_day(as_of=as_of, limit=max(limit * 4, 40))
    except Exception:  # noqa: BLE001 — report must not die if events absent
        return []

    scored: list[tuple[int, EventRow]] = []
    for row in rows:
        raw_symbols = row.get("symbols") or []
        symbols = [str(s) for s in cast(list[Any], raw_symbols) if s]
        in_uni = 1 if (uni and any(s in uni for s in symbols)) else 0
        impact_raw = row.get("impact")
        impact = float(cast(Any, impact_raw)) if impact_raw is not None else 0.0
        news_id = row.get("news_id")
        news_source = row.get("news_source")
        scored.append(
            (
                in_uni * 10 + int(impact * 10),
                EventRow(
                    event_id=int(cast(Any, row["event_id"])),
                    news_id=int(cast(Any, news_id)) if news_id is not None else None,
                    event_type=str(row["event_type"]),
                    summary=str(row["summary"])[:200],
                    direction=str(row.get("direction") or "unclear"),
                    impact=impact if impact_raw is not None else None,
                    symbols=symbols[:5],
                    news_source=str(news_source) if news_source else None,
                ),
            )
        )
    scored.sort(key=lambda x: (-x[0], -x[1].event_id))
    return [item for _, item in scored[:limit]]


def event_rows_to_dicts(rows: list[EventRow]) -> list[dict[str, Any]]:
    return [r.model_dump() for r in rows]
