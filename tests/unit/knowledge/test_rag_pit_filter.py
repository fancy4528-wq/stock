"""Pure-logic sentinel: expires_at / visible_at filter mirrors SQL."""

from __future__ import annotations

from datetime import UTC, datetime


def _sql_filter(
    rows: list[dict[str, object]],
    *,
    as_of: datetime,
) -> list[dict[str, object]]:
    """Mirror ``search_chunks_as_of`` time predicates for unit testing."""
    out: list[dict[str, object]] = []
    for r in rows:
        visible = r["visible_at"]
        expires = r.get("expires_at")
        assert isinstance(visible, datetime)
        if visible > as_of:
            continue
        if expires is not None:
            assert isinstance(expires, datetime)
            if expires <= as_of:
                continue
        out.append(r)
    return out


def test_visible_at_and_expires_bidirectional() -> None:
    as_of = datetime(2020, 6, 1, 15, 0, tzinfo=UTC)
    rows = [
        {
            "chunk_id": 1,
            "content": "past ok",
            "visible_at": datetime(2019, 1, 1, tzinfo=UTC),
            "expires_at": None,
        },
        {
            "chunk_id": 2,
            "content": "future leak",
            "visible_at": datetime(2021, 1, 1, tzinfo=UTC),
            "expires_at": None,
        },
        {
            "chunk_id": 3,
            "content": "expired rule",
            "visible_at": datetime(2015, 1, 1, tzinfo=UTC),
            "expires_at": datetime(2018, 1, 1, tzinfo=UTC),
        },
        {
            "chunk_id": 4,
            "content": "still in force",
            "visible_at": datetime(2019, 6, 1, tzinfo=UTC),
            "expires_at": datetime(2025, 1, 1, tzinfo=UTC),
        },
    ]
    kept = _sql_filter(rows, as_of=as_of)
    assert [r["chunk_id"] for r in kept] == [1, 4]
