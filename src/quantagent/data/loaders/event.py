"""Persist ``EventExtraction`` rows into ``event`` / ``event_security``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from quantagent.agents.news_extractor.schema import EventExtraction
from quantagent.data.normalizers.news import symbol_from_em_announce_url
from quantagent.data.normalizers.symbol import normalize_symbol, to_raw_digits
from quantagent.shared.config import get_settings
from quantagent.shared.errors import DataError


def _infer_board(digits: str) -> str:
    if digits.startswith("68"):
        return "star"
    if digits.startswith("30"):
        return "gem"
    if digits.startswith(("43", "83", "87", "88", "92")):
        return "bse"
    return "main"


def _impact_from_magnitude(magnitude: str) -> float:
    return {"minor": 0.25, "moderate": 0.5, "major": 0.85}.get(magnitude, 0.4)


class EventLoader:
    """Insert structured events linked to ``news`` and optional securities."""

    def __init__(self, engine: Engine | None = None) -> None:
        if engine is not None:
            self._engine = engine
        else:
            self._engine = create_engine(get_settings().database_url, pool_pre_ping=True)

    def load_extractions(
        self,
        items: list[tuple[int, datetime, EventExtraction]],
        *,
        extractor_model: str,
        extractor_version: str,
        skip_irrelevant: bool = True,
    ) -> dict[str, int]:
        if not items:
            return {"events": 0, "links": 0}

        events = 0
        links = 0
        with self._engine.begin() as conn:
            for news_id, visible_at, extraction in items:
                if skip_irrelevant and not extraction.is_relevant:
                    continue
                event_id = self._insert_event(
                    conn,
                    news_id=news_id,
                    visible_at=visible_at,
                    extraction=extraction,
                    extractor_model=extractor_model,
                    extractor_version=extractor_version,
                )
                events += 1
                links += self._link_securities(conn, event_id=event_id, extraction=extraction)
        return {"events": events, "links": links}

    def _insert_event(
        self,
        conn: Connection,
        *,
        news_id: int,
        visible_at: datetime,
        extraction: EventExtraction,
        extractor_model: str,
        extractor_version: str,
    ) -> int:
        figures = [f.model_dump() for f in extraction.figures]
        event_id = conn.execute(
            text(
                """
                INSERT INTO event (
                    news_id, occurred_at, visible_at, event_type, summary,
                    direction, impact, horizon, confidence, figures,
                    extractor_model, extractor_version, extracted_at
                ) VALUES (
                    :news_id, :occurred_at, :visible_at, :event_type, :summary,
                    :direction, :impact, :horizon, :confidence, CAST(:figures AS jsonb),
                    :extractor_model, :extractor_version, :extracted_at
                )
                RETURNING event_id
                """
            ),
            {
                "news_id": news_id,
                "occurred_at": visible_at,
                "visible_at": visible_at,
                "event_type": extraction.event_type,
                "summary": extraction.summary[:500],
                "direction": extraction.direction,
                "impact": _impact_from_magnitude(extraction.magnitude),
                "horizon": extraction.horizon,
                "confidence": extraction.confidence,
                "figures": json.dumps(figures, ensure_ascii=False),
                "extractor_model": extractor_model,
                "extractor_version": extractor_version,
                "extracted_at": datetime.now(UTC),
            },
        ).scalar_one()
        return int(event_id)

    def _ensure_security(self, conn: Connection, symbol: str) -> int | None:
        try:
            canon = normalize_symbol(symbol, market="CN")
            digits = to_raw_digits(canon)
        except ValueError:
            return None
        board = _infer_board(digits)
        sec_id = conn.execute(
            text(
                """
                INSERT INTO security (market, symbol, raw_symbol, name, board, currency)
                VALUES ('CN', :symbol, :raw, :name, :board, 'CNY')
                ON CONFLICT (market, symbol) DO UPDATE
                  SET raw_symbol = EXCLUDED.raw_symbol
                RETURNING security_id
                """
            ),
            {
                "symbol": canon,
                "raw": digits,
                "name": canon,
                "board": board,
            },
        ).scalar_one()
        return int(sec_id)

    def _link_securities(
        self,
        conn: Connection,
        *,
        event_id: int,
        extraction: EventExtraction,
    ) -> int:
        n = 0
        for symbol in extraction.primary_symbols:
            sec_id = self._ensure_security(conn, symbol)
            if sec_id is None:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO event_security (event_id, security_id, relation, impact)
                    VALUES (:event_id, :security_id, 'subject', :impact)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "event_id": event_id,
                    "security_id": sec_id,
                    "impact": _impact_from_magnitude(extraction.magnitude),
                },
            )
            n += 1
        for related in extraction.related_symbols:
            sec_id = self._ensure_security(conn, related.symbol)
            if sec_id is None:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO event_security (event_id, security_id, relation, impact)
                    VALUES (:event_id, :security_id, :relation, :impact)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "event_id": event_id,
                    "security_id": sec_id,
                    "relation": related.relation,
                    "impact": _impact_from_magnitude(extraction.magnitude),
                },
            )
            n += 1
        return n

    def fetch_unextracted_news(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return news rows that do not yet have a rule_v1 event."""
        if limit < 1:
            raise DataError("limit must be >= 1")
        params: dict[str, Any] = {"limit": limit}
        since_clause = ""
        if since is not None:
            since_clause = "AND n.published_at >= :since"
            params["since"] = since
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        f"""
                        SELECT n.news_id, n.title, n.body, n.published_at, n.source,
                               n.url, n.related_symbol, n.announce_type
                        FROM news n
                        WHERE NOT EXISTS (
                            SELECT 1 FROM event e
                            WHERE e.news_id = n.news_id
                              AND e.extractor_model = 'rule_v1'
                        )
                        {since_clause}
                        ORDER BY n.published_at DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if not item.get("related_symbol"):
                item["related_symbol"] = symbol_from_em_announce_url(item.get("url"))
            out.append(item)
        return out

    def backfill_related_symbols_from_urls(self) -> int:
        """Fill ``news.related_symbol`` from EM notice URLs when missing."""
        updated = 0
        with self._engine.begin() as conn:
            rows = (
                conn.execute(
                    text(
                        """
                        SELECT news_id, url
                        FROM news
                        WHERE related_symbol IS NULL
                          AND url IS NOT NULL
                          AND source = 'em_announce'
                        """
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                symbol = symbol_from_em_announce_url(row["url"])
                if not symbol:
                    continue
                conn.execute(
                    text(
                        """
                        UPDATE news
                        SET related_symbol = :symbol
                        WHERE news_id = :news_id
                          AND related_symbol IS NULL
                        """
                    ),
                    {"symbol": symbol, "news_id": int(row["news_id"])},
                )
                updated += 1
        return updated

    def backfill_subject_links_from_news(self, *, limit: int | None = None) -> dict[str, int]:
        """Attach subject ``event_security`` rows using ``news.related_symbol``.

        Targets events that have a related symbol on the parent news row but no
        subject link yet (typical after announcement extract without hints).
        """
        params: dict[str, Any] = {}
        limit_clause = ""
        if limit is not None:
            if limit < 1:
                raise DataError("limit must be >= 1")
            limit_clause = "LIMIT :limit"
            params["limit"] = limit

        linked = 0
        scanned = 0
        with self._engine.begin() as conn:
            rows = (
                conn.execute(
                    text(
                        f"""
                        SELECT e.event_id, e.impact, n.related_symbol, n.url
                        FROM event e
                        JOIN news n ON n.news_id = e.news_id
                        WHERE NOT EXISTS (
                            SELECT 1 FROM event_security es
                            WHERE es.event_id = e.event_id
                              AND es.relation = 'subject'
                        )
                          AND (
                            n.related_symbol IS NOT NULL
                            OR (n.source = 'em_announce' AND n.url IS NOT NULL)
                          )
                        ORDER BY e.event_id
                        {limit_clause}
                        """
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            for row in rows:
                scanned += 1
                symbol = row["related_symbol"] or symbol_from_em_announce_url(row["url"])
                if not symbol:
                    continue
                sec_id = self._ensure_security(conn, str(symbol))
                if sec_id is None:
                    continue
                impact = row["impact"]
                result = conn.execute(
                    text(
                        """
                        INSERT INTO event_security (event_id, security_id, relation, impact)
                        VALUES (:event_id, :security_id, 'subject', :impact)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "event_id": int(row["event_id"]),
                        "security_id": sec_id,
                        "impact": float(impact) if impact is not None else 0.4,
                    },
                )
                if result.rowcount:
                    linked += 1
        return {"scanned": scanned, "linked": linked}
