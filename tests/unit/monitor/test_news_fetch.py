"""Unit tests: monitor news fetch helpers (no network)."""

from __future__ import annotations

from pathlib import Path

from quantagent.monitor import announcements_fetch, news_fetch
from quantagent.monitor.news_fetch import _merge_dedupe
from quantagent.monitor.triggers.news import NewsFeedItem


def test_merge_dedupe_by_hash_and_title() -> None:
    a = NewsFeedItem(title="同一条", content_hash="h1", news_id=1)
    b = NewsFeedItem(title="同一条", content_hash="h1", news_id=2)
    c = NewsFeedItem(title="另一条", content_hash="h2", news_id=3)
    merged = _merge_dedupe([a], [b, c], limit=10)
    assert len(merged) == 2
    assert {m.content_hash for m in merged} == {"h1", "h2"}


def test_lookback_queries_are_closed_at_now() -> None:
    news_src = Path(news_fetch.__file__).read_text(encoding="utf-8")
    ann_src = Path(announcements_fetch.__file__).read_text(encoding="utf-8")
    assert "published_at <= :until" in news_src
    assert "published_at <= :until" in ann_src
