"""Load structured events for a report ``as_of`` session (PIT by visible_at)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from quantagent.agents.tools.market import EventRow
from quantagent.shared.config import get_settings

CN_TZ = ZoneInfo("Asia/Shanghai")


def _session_bounds(as_of: date) -> tuple[datetime, datetime]:
    """Inclusive window: calendar day in Asia/Shanghai."""
    start = datetime.combine(as_of, time(0, 0), tzinfo=CN_TZ)
    end = datetime.combine(as_of, time(23, 59, 59, 999999), tzinfo=CN_TZ)
    return start, end


def load_events_for_as_of(
    as_of: date,
    *,
    limit: int = 12,
    engine: Engine | None = None,
    universe_symbols: list[str] | None = None,
) -> list[EventRow]:
    """Return events with ``visible_at`` on ``as_of`` (Shanghai calendar day).

    Prefers events linked to ``universe_symbols`` when provided, then by impact.
    Soft-fails to ``[]`` if ``event`` / ``news`` tables are missing.
    """
    eng = engine or create_engine(get_settings().database_url, pool_pre_ping=True)
    start, end = _session_bounds(as_of)
    uni = set(universe_symbols or [])

    sql = text(
        """
        SELECT
            e.event_id,
            e.news_id,
            e.event_type,
            e.summary,
            e.direction,
            e.impact,
            e.visible_at,
            n.source AS news_source,
            COALESCE(
                array_agg(DISTINCT s.symbol) FILTER (WHERE s.symbol IS NOT NULL),
                ARRAY[]::text[]
            ) AS symbols
        FROM event e
        LEFT JOIN news n ON n.news_id = e.news_id
        LEFT JOIN event_security es ON es.event_id = e.event_id
        LEFT JOIN security s ON s.security_id = es.security_id
        WHERE e.visible_at >= :start
          AND e.visible_at <= :end
        GROUP BY
            e.event_id, e.news_id, e.event_type, e.summary,
            e.direction, e.impact, e.visible_at, n.source
        ORDER BY e.impact DESC NULLS LAST, e.event_id DESC
        LIMIT :limit_fetch
        """
    )
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                sql,
                {"start": start, "end": end, "limit_fetch": max(limit * 4, 40)},
            ).mappings().all()
    except Exception:  # noqa: BLE001 — report must not die if events absent
        return []

    scored: list[tuple[int, EventRow]] = []
    for row in rows:
        symbols = [str(s) for s in (row["symbols"] or []) if s]
        in_uni = 1 if (uni and any(s in uni for s in symbols)) else 0
        impact = float(row["impact"] or 0.0)
        scored.append(
            (
                in_uni * 10 + int(impact * 10),
                EventRow(
                    event_id=int(row["event_id"]),
                    news_id=int(row["news_id"]) if row["news_id"] is not None else None,
                    event_type=str(row["event_type"]),
                    summary=str(row["summary"])[:200],
                    direction=str(row["direction"] or "unclear"),
                    impact=impact if row["impact"] is not None else None,
                    symbols=symbols[:5],
                    news_source=str(row["news_source"]) if row["news_source"] else None,
                ),
            )
        )
    scored.sort(key=lambda x: (-x[0], -x[1].event_id))
    return [item for _, item in scored[:limit]]


def event_rows_to_dicts(rows: list[EventRow]) -> list[dict[str, Any]]:
    return [r.model_dump() for r in rows]
