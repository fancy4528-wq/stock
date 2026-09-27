"""Unit tests: monitor news fetch helpers (no network)."""

from __future__ import annotations

from quantagent.monitor.news_fetch import _merge_dedupe
from quantagent.monitor.triggers.news import NewsFeedItem


def test_merge_dedupe_by_hash_and_title() -> None:
    a = NewsFeedItem(title="同一条", content_hash="h1", news_id=1)
    b = NewsFeedItem(title="同一条", content_hash="h1", news_id=2)
    c = NewsFeedItem(title="另一条", content_hash="h2", news_id=3)
    merged = _merge_dedupe([a], [b, c], limit=10)
    assert len(merged) == 2
    assert {m.content_hash for m in merged} == {"h1", "h2"}
