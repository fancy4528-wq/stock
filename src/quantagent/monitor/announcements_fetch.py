"""Fetch recent announcements for holdings from DB (live monitor, not PIT backtest)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine

from quantagent.monitor.triggers.announcement import AnnouncementItem
from quantagent.shared.config import get_settings


def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def fetch_holding_announcements(
    symbols: Sequence[str],
    *,
    lookback_hours: int = 72,
    limit: int = 200,
    engine: Engine | None = None,
    now: datetime | None = None,
) -> list[AnnouncementItem]:
    """Load recent ``news`` rows with ``related_symbol`` in holdings/watchlist.

    Soft-fails to ``[]`` if DB is unreachable or table missing.
    """
    syms = sorted({s for s in symbols if s})
    if not syms:
        return []
    when = now or datetime.now(UTC)
    since = when - timedelta(hours=int(lookback_hours))
    eng = engine or _engine()
    stmt = text(
        """
        SELECT
            news_id, source, url, title, announce_type,
            related_symbol, published_at
        FROM news
        WHERE related_symbol IN :symbols
          AND published_at >= :since
        ORDER BY published_at DESC, news_id DESC
        LIMIT :lim
        """
    ).bindparams(bindparam("symbols", expanding=True))
    try:
        with eng.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {"symbols": list(syms), "since": since, "lim": int(limit)},
                )
                .mappings()
                .all()
            )
    except Exception:  # noqa: BLE001 — monitor must soft-fail
        return []

    out: list[AnnouncementItem] = []
    for r in rows:
        sym = r.get("related_symbol")
        if not sym:
            continue
        pub = r.get("published_at")
        out.append(
            AnnouncementItem(
                symbol=str(sym),
                title=str(r.get("title") or ""),
                announce_type=(str(r["announce_type"]) if r.get("announce_type") else None),
                news_id=int(r["news_id"]) if r.get("news_id") is not None else None,
                published_at=pub if isinstance(pub, datetime) else None,
                source=str(r["source"]) if r.get("source") else None,
                url=str(r["url"]) if r.get("url") else None,
            )
        )
    return out
