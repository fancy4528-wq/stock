"""Fetch recent flash news for D-class L1 filter (P2b). Soft-fail; zero LLM."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.news import content_hash
from quantagent.monitor.triggers.news import NewsFeedItem
from quantagent.shared.config import get_settings

logger = logging.getLogger(__name__)

# C-class owns em_announce; D-class is flash / telegraph only.
_FLASH_SOURCES = ("cls", "em")


def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def fetch_news_from_db(
    *,
    lookback_hours: int = 24,
    limit: int = 300,
    engine: Engine | None = None,
    now: datetime | None = None,
    sources: Sequence[str] = _FLASH_SOURCES,
) -> list[NewsFeedItem]:
    """Load recent flash ``news`` rows (cls/em). Soft-fails to ``[]``."""
    srcs = [s for s in sources if s]
    if not srcs:
        return []
    when = now or datetime.now(UTC)
    since = when - timedelta(hours=int(lookback_hours))
    eng = engine or _engine()
    # Expanding IN for sources — use ANY-style via bindparam if needed;
    # small fixed set: inline placeholders safely.
    placeholders = ", ".join(f":s{i}" for i in range(len(srcs)))
    stmt = text(
        f"""
        SELECT
            news_id, source, url, title, body,
            related_symbol, published_at, content_hash
        FROM news
        WHERE source IN ({placeholders})
          AND published_at >= :since
        ORDER BY published_at DESC, news_id DESC
        LIMIT :lim
        """
    )
    params: dict[str, Any] = {"since": since, "lim": int(limit)}
    for i, s in enumerate(srcs):
        params[f"s{i}"] = s
    try:
        with eng.connect() as conn:
            rows = conn.execute(stmt, params).mappings().all()
    except Exception:  # noqa: BLE001 — monitor must soft-fail
        return []

    out: list[NewsFeedItem] = []
    for r in rows:
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        body = r.get("body")
        pub = r.get("published_at")
        out.append(
            NewsFeedItem(
                title=title,
                summary=(str(body)[:200] if body else None),
                news_id=int(r["news_id"]) if r.get("news_id") is not None else None,
                published_at=pub if isinstance(pub, datetime) else None,
                source=str(r["source"]) if r.get("source") else None,
                url=str(r["url"]) if r.get("url") else None,
                content_hash=str(r["content_hash"]) if r.get("content_hash") else None,
                related_symbol=(
                    str(r["related_symbol"]) if r.get("related_symbol") else None
                ),
            )
        )
    return out


def fetch_live_cls_flash(*, limit: int = 80) -> list[NewsFeedItem]:
    """Pull rolling CLS telegraph via akshare (no DB write). Soft-fails to ``[]``."""
    try:
        apply_proxy_bypass()
        import akshare as ak

        pdf = ak.stock_info_global_cls()
    except Exception as exc:  # noqa: BLE001
        logger.debug("live CLS flash failed: %s", exc)
        return []
    if pdf is None or getattr(pdf, "empty", True):
        return []

    out: list[NewsFeedItem] = []
    try:
        records = pdf.to_dict(orient="records")
    except Exception:  # noqa: BLE001
        return []
    for row in records:
        title = str(row.get("标题") or "").strip()
        if not title:
            continue
        body_raw = str(row.get("内容") or "").strip() or None
        ch = content_hash(title, body_raw)
        out.append(
            NewsFeedItem(
                title=title,
                summary=(body_raw[:200] if body_raw else None),
                source="cls",
                content_hash=ch,
            )
        )
        if len(out) >= int(limit):
            break
    return out


def fetch_monitor_news(
    *,
    lookback_hours: int = 24,
    limit: int = 300,
    include_live_flash: bool = True,
    engine: Engine | None = None,
    now: datetime | None = None,
) -> list[NewsFeedItem]:
    """DB flash news, optionally merged with live CLS flash (dedupe by hash/title)."""
    items = fetch_news_from_db(
        lookback_hours=lookback_hours, limit=limit, engine=engine, now=now
    )
    if include_live_flash:
        live = fetch_live_cls_flash(limit=min(80, limit))
        items = _merge_dedupe(items, live, limit=limit)
    return items


def _merge_dedupe(
    primary: list[NewsFeedItem],
    extra: list[NewsFeedItem],
    *,
    limit: int,
) -> list[NewsFeedItem]:
    seen: set[str] = set()
    out: list[NewsFeedItem] = []
    for item in [*primary, *extra]:
        key = item.content_hash or item.title.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out
