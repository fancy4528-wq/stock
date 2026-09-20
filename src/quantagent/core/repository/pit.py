"""Point-in-time data access — sole historical query entrypoint."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import Connection, bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, BIGINT, TEXT
from sqlalchemy.engine import Engine

from quantagent.core.assertions import assert_no_lookahead
from quantagent.shared.config import Settings, get_settings
from quantagent.shared.errors import LookaheadError

CN_TZ = ZoneInfo("Asia/Shanghai")


class PITRepository:
    """All historical reads go through here; ``as_of`` is always required."""

    def __init__(
        self,
        engine: Engine | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        if engine is not None:
            self._engine = engine
        else:
            cfg = settings or get_settings()
            self._engine = create_engine(cfg.database_url, pool_pre_ping=True)

    @staticmethod
    def _eod(d: date) -> datetime:
        """Map calendar date to A-share session close (15:00 Asia/Shanghai)."""
        return datetime.combine(d, time(15, 0), tzinfo=CN_TZ)

    def _resolve_symbol_ids(self, conn: Connection, symbols: list[str]) -> dict[str, int]:
        if not symbols:
            return {}
        stmt = text(
            "SELECT security_id, symbol FROM security WHERE symbol = ANY(:symbols)"
        ).bindparams(bindparam("symbols", type_=ARRAY(TEXT())))
        result = conn.execute(stmt, {"symbols": symbols})
        by_symbol = {row.symbol: int(row.security_id) for row in result}
        missing = [s for s in symbols if s not in by_symbol]
        if missing:
            raise KeyError(f"Unknown symbols: {missing}")
        return by_symbol

    def _resolve_ids(self, conn: Connection, symbols: list[str]) -> list[int]:
        by_symbol = self._resolve_symbol_ids(conn, symbols)
        return [by_symbol[s] for s in symbols]

    def get_delisted_between(self, start: date, end: date) -> list[str]:
        """Symbols with ``delist_date`` in ``[start, end]`` (inclusive)."""
        if end < start:
            return []
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT symbol
                    FROM security
                    WHERE delist_date IS NOT NULL
                      AND delist_date >= :start
                      AND delist_date <= :end
                    ORDER BY symbol
                    """
                ),
                {"start": start, "end": end},
            ).fetchall()
        return [str(r[0]) for r in rows]

    def get_security_names(self, symbols: list[str], *, as_of: date) -> dict[str, str]:
        """Return ``symbol -> name`` for known securities (empty dict if none)."""
        _ = as_of  # current name lookup; signature enforces PIT discipline at call sites
        if not symbols:
            return {}
        with self._engine.connect() as conn:
            stmt = text(
                "SELECT symbol, name FROM security WHERE symbol = ANY(:symbols)"
            ).bindparams(bindparam("symbols", type_=ARRAY(TEXT())))
            rows = conn.execute(stmt, {"symbols": symbols}).mappings().all()
        return {str(r["symbol"]): str(r["name"]) for r in rows}

    def resolve_universe_symbols(self, *, as_of: date, name: str) -> list[str]:
        """Map ``get_universe`` security_ids to symbols (snapshot order)."""
        uni = self.get_universe(as_of=as_of, name=name)
        if uni.is_empty():
            return []
        ids = [int(x) for x in uni["security_id"].to_list()]
        with self._engine.connect() as conn:
            stmt = text(
                "SELECT security_id, symbol FROM security WHERE security_id = ANY(:ids)"
            ).bindparams(bindparam("ids", type_=ARRAY(BIGINT())))
            rows = conn.execute(stmt, {"ids": ids}).mappings().all()
        by_id = {int(r["security_id"]): str(r["symbol"]) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def list_universe_snapshot_dates(self, *, name: str) -> list[date]:
        """Return available ``universe_snapshot.snapshot_date`` values (ascending)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT us.snapshot_date
                    FROM universe_snapshot us
                    JOIN universe u ON u.universe_id = us.universe_id
                    WHERE u.code = :code
                    ORDER BY us.snapshot_date
                    """
                ),
                {"code": name},
            ).fetchall()
        out: list[date] = []
        for (d,) in rows:
            if d is None:
                continue
            out.append(d if isinstance(d, date) else date.fromisoformat(str(d)))
        return out

    def latest_trade_date(self, symbols: list[str], *, as_of: date) -> date | None:
        """Max ``trade_date`` in ``price_daily`` for symbols with ``trade_date <= as_of``."""
        if not symbols:
            return None
        with self._engine.connect() as conn:
            sec_ids = self._resolve_ids(conn, symbols)
            if not sec_ids:
                return None
            stmt = text(
                """
                SELECT max(trade_date) AS d
                FROM price_daily
                WHERE security_id = ANY(:ids)
                  AND trade_date <= :as_of
                """
            ).bindparams(bindparam("ids", type_=ARRAY(BIGINT())))
            row = conn.execute(stmt, {"ids": sec_ids, "as_of": as_of}).mappings().one()
        d = row["d"]
        if d is None:
            return None
        if isinstance(d, date):
            return d
        return date.fromisoformat(str(d))

    def get_financials(
        self,
        symbols: list[str],
        *,
        as_of: date,
        periods: int = 8,
    ) -> pl.DataFrame:
        with self._engine.connect() as conn:
            sec_ids = self._resolve_ids(conn, symbols)
            if not sec_ids:
                return pl.DataFrame()
            stmt = text("SELECT * FROM get_financials_as_of(:ids, :as_of, :periods)").bindparams(
                bindparam("ids", type_=ARRAY(BIGINT))
            )
            rows = (
                conn.execute(
                    stmt,
                    {"ids": sec_ids, "as_of": self._eod(as_of), "periods": periods},
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty():
            df = df.with_columns(pl.lit(as_of).alias("_as_of"))
            assert_no_lookahead(df, self._eod(as_of), "announced_at")
        return df

    def get_prices(
        self,
        symbols: list[str],
        *,
        as_of: date,
        start: date,
        end: date | None = None,
        adjust: str = "qfq",
    ) -> pl.DataFrame:
        end_date = end or as_of
        with self._engine.connect() as conn:
            by_symbol = self._resolve_symbol_ids(conn, symbols)
            sec_ids = [by_symbol[s] for s in symbols]
            if not sec_ids:
                return pl.DataFrame()
            stmt = text(
                "SELECT * FROM get_prices_as_of(:ids, :start, :end, :as_of, :adjust)"
            ).bindparams(bindparam("ids", type_=ARRAY(BIGINT)))
            rows = (
                conn.execute(
                    stmt,
                    {
                        "ids": sec_ids,
                        "start": start,
                        "end": end_date,
                        "as_of": self._eod(as_of),
                        "adjust": adjust,
                    },
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty():
            id_to_symbol = {sid: sym for sym, sid in by_symbol.items()}
            df = df.with_columns(
                [
                    pl.col("security_id")
                    .replace_strict(id_to_symbol, return_dtype=pl.Utf8)
                    .alias("symbol"),
                    pl.lit(as_of).alias("_as_of"),
                ]
            )
            assert_no_lookahead(df, as_of, "trade_date")
        return df

    def get_industry(
        self,
        symbols: list[str],
        *,
        as_of: date,
        taxonomy: str = "sw_2021",
    ) -> pl.DataFrame:
        with self._engine.connect() as conn:
            by_symbol = self._resolve_symbol_ids(conn, symbols)
            sec_ids = [by_symbol[s] for s in symbols]
            if not sec_ids:
                return pl.DataFrame()
            stmt = text("SELECT * FROM get_industry_as_of(:ids, :as_of, :taxonomy)").bindparams(
                bindparam("ids", type_=ARRAY(BIGINT))
            )
            rows = (
                conn.execute(
                    stmt,
                    {"ids": sec_ids, "as_of": as_of, "taxonomy": taxonomy},
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty():
            id_to_symbol = {sid: sym for sym, sid in by_symbol.items()}
            df = df.with_columns(
                pl.col("security_id")
                .replace_strict(id_to_symbol, return_dtype=pl.Utf8)
                .alias("symbol")
            )
            if "valid_from" in df.columns:
                assert_no_lookahead(df, as_of, "valid_from")
        return df

    def get_universe(self, *, as_of: date, name: str) -> pl.DataFrame:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text("SELECT * FROM get_universe_as_of(:code, :as_of)"),
                    {"code": name, "as_of": as_of},
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty() and "snapshot_date" in df.columns:
            assert_no_lookahead(df, as_of, "snapshot_date")
        return df

    def search_chunks(
        self,
        embedding: list[float],
        *,
        as_of: date,
        limit: int = 5,
        security_id: int | None = None,
    ) -> list[dict[str, object]]:
        """RAG search via ``search_chunks_as_of`` (sole SQL entry for chunks).

        Enforces ``visible_at <= as_of`` and ``expires_at`` bidirectional filter
        inside the SQL function. ``as_of`` is keyword-only (no default).
        """
        if limit <= 0:
            return []
        if not embedding:
            raise ValueError("embedding must be non-empty")
        vec = "[" + ",".join(f"{float(x):.8f}" for x in embedding) + "]"
        stmt = text(
            """
            SELECT chunk_id, content, doc_type, doc_ref, security_id, visible_at, distance
            FROM search_chunks_as_of(
                CAST(:embedding AS vector),
                :as_of,
                :limit,
                :security_id
            )
            """
        )
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {
                        "embedding": vec,
                        "as_of": self._eod(as_of),
                        "limit": int(limit),
                        "security_id": security_id,
                    },
                )
                .mappings()
                .all()
            )
        out = [dict(r) for r in rows]
        # Runtime guard: no row may be visible after as_of EOD.
        as_of_ts = self._eod(as_of)
        for row in out:
            visible = row.get("visible_at")
            if isinstance(visible, datetime) and visible > as_of_ts:
                raise LookaheadError(
                    f"search_chunks returned future visible_at={visible} as_of={as_of_ts}"
                )
        return out

    def fetch_events_on_day(
        self,
        *,
        as_of: date,
        limit: int = 40,
    ) -> list[dict[str, object]]:
        """Events with ``visible_at`` on the Shanghai calendar day of ``as_of``.

        Returns raw mapping rows (symbols as list). Raises on DB errors so
        callers can soft-fail for optional report sections.
        """
        start = datetime.combine(as_of, time(0, 0), tzinfo=CN_TZ)
        end = datetime.combine(as_of, time(23, 59, 59, 999999), tzinfo=CN_TZ)
        stmt = text(
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
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {"start": start, "end": end, "limit_fetch": int(limit)},
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    def get_financial_indicators(
        self,
        symbols: list[str],
        *,
        as_of: date,
        periods: int = 8,
    ) -> pl.DataFrame:
        """PIT financial indicators (``announced_at <= as_of``, latest revision)."""
        with self._engine.connect() as conn:
            by_symbol = self._resolve_symbol_ids(conn, symbols)
            sec_ids = [by_symbol[s] for s in symbols]
            if not sec_ids:
                return pl.DataFrame()
            stmt = text(
                """
                WITH visible AS (
                    SELECT DISTINCT ON (security_id, period_end) *
                    FROM financial_indicator
                    WHERE security_id = ANY(:ids)
                      AND announced_at <= :as_of
                    ORDER BY security_id, period_end, revision DESC
                ),
                ranked AS (
                    SELECT
                        visible.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY security_id
                            ORDER BY period_end DESC
                        ) AS rn
                    FROM visible
                )
                SELECT
                    security_id, period_end, revision, announced_at,
                    roe, roa, gross_margin, net_margin, debt_to_asset,
                    current_ratio, revenue_yoy, profit_yoy, ocf_to_profit,
                    source, ingested_at
                FROM ranked
                WHERE rn <= :periods
                """
            ).bindparams(bindparam("ids", type_=ARRAY(BIGINT())))
            rows = (
                conn.execute(
                    stmt,
                    {
                        "ids": sec_ids,
                        "as_of": self._eod(as_of),
                        "periods": int(periods),
                    },
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty():
            id_to_symbol = {sid: sym for sym, sid in by_symbol.items()}
            df = df.with_columns(
                [
                    pl.col("security_id")
                    .replace_strict(id_to_symbol, return_dtype=pl.Utf8)
                    .alias("symbol"),
                    pl.lit(as_of).alias("_as_of"),
                ]
            )
            assert_no_lookahead(df, self._eod(as_of), "announced_at")
        return df

    def get_valuation(
        self,
        symbols: list[str],
        *,
        as_of: date,
        start: date,
        end: date | None = None,
    ) -> pl.DataFrame:
        """Daily valuation panel with ``trade_date <= as_of``."""
        end_date = end or as_of
        if end_date > as_of:
            end_date = as_of
        with self._engine.connect() as conn:
            by_symbol = self._resolve_symbol_ids(conn, symbols)
            sec_ids = [by_symbol[s] for s in symbols]
            if not sec_ids:
                return pl.DataFrame()
            stmt = text(
                """
                SELECT
                    security_id, trade_date, market_cap, circ_market_cap,
                    pe_ttm, pe_lyr, pb, ps_ttm, dividend_yield, source
                FROM valuation_daily
                WHERE security_id = ANY(:ids)
                  AND trade_date >= :start
                  AND trade_date <= :end
                ORDER BY security_id, trade_date
                """
            ).bindparams(bindparam("ids", type_=ARRAY(BIGINT())))
            rows = (
                conn.execute(
                    stmt,
                    {"ids": sec_ids, "start": start, "end": end_date},
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty():
            id_to_symbol = {sid: sym for sym, sid in by_symbol.items()}
            df = df.with_columns(
                [
                    pl.col("security_id")
                    .replace_strict(id_to_symbol, return_dtype=pl.Utf8)
                    .alias("symbol"),
                    pl.lit(as_of).alias("_as_of"),
                ]
            )
            assert_no_lookahead(df, as_of, "trade_date")
        return df

    def get_news(
        self,
        *,
        as_of: date,
        start: date,
        limit: int = 20,
        sources: list[str] | None = None,
        related_symbol: str | None = None,
    ) -> list[dict[str, object]]:
        """News / announcements with ``published_at`` in ``[start, as_of]`` EOD."""
        start_ts = datetime.combine(start, time(0, 0), tzinfo=CN_TZ)
        end_ts = self._eod(as_of)
        src = sources or []
        stmt = text(
            """
            SELECT
                news_id, source, source_id, url, title,
                left(COALESCE(body, ''), 800) AS body_excerpt,
                published_at, related_symbol, announce_type
            FROM news
            WHERE published_at >= :start_ts
              AND published_at <= :end_ts
              AND (cardinality(:sources) = 0 OR source = ANY(:sources))
              AND (
                    :related_symbol IS NULL
                    OR related_symbol = :related_symbol
                  )
            ORDER BY published_at DESC, news_id DESC
            LIMIT :limit_fetch
            """
        ).bindparams(bindparam("sources", type_=ARRAY(TEXT())))
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "sources": src,
                        "related_symbol": related_symbol,
                        "limit_fetch": int(limit),
                    },
                )
                .mappings()
                .all()
            )
        out = [dict(r) for r in rows]
        for row in out:
            pub = row.get("published_at")
            if isinstance(pub, datetime) and pub > end_ts:
                raise LookaheadError(
                    f"get_news returned future published_at={pub} as_of={end_ts}"
                )
        return out

    def get_events(
        self,
        *,
        as_of: date,
        start: date,
        limit: int = 40,
        symbol: str | None = None,
        event_types: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Structured events with ``visible_at`` in ``[start, as_of]`` EOD."""
        start_ts = datetime.combine(start, time(0, 0), tzinfo=CN_TZ)
        end_ts = self._eod(as_of)
        types = event_types or []
        stmt = text(
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
            WHERE e.visible_at >= :start_ts
              AND e.visible_at <= :end_ts
              AND (cardinality(:event_types) = 0 OR e.event_type = ANY(:event_types))
              AND (
                    :symbol IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM event_security es2
                        JOIN security s2 ON s2.security_id = es2.security_id
                        WHERE es2.event_id = e.event_id
                          AND s2.symbol = :symbol
                    )
                  )
            GROUP BY
                e.event_id, e.news_id, e.event_type, e.summary,
                e.direction, e.impact, e.visible_at, n.source
            ORDER BY e.impact DESC NULLS LAST, e.visible_at DESC, e.event_id DESC
            LIMIT :limit_fetch
            """
        ).bindparams(bindparam("event_types", type_=ARRAY(TEXT())))
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "event_types": types,
                        "symbol": symbol,
                        "limit_fetch": int(limit),
                    },
                )
                .mappings()
                .all()
            )
        out = [dict(r) for r in rows]
        for row in out:
            visible = row.get("visible_at")
            if isinstance(visible, datetime) and visible > end_ts:
                raise LookaheadError(
                    f"get_events returned future visible_at={visible} as_of={end_ts}"
                )
        return out

    def get_industry_members(
        self,
        industry_code: str,
        *,
        as_of: date,
        taxonomy: str = "sw_2021",
        limit: int = 200,
    ) -> pl.DataFrame:
        """Securities in an industry as of ``as_of`` (PIT membership)."""
        stmt = text(
            """
            SELECT
                s.security_id,
                s.symbol,
                s.name,
                i.code AS industry_code,
                i.name AS industry_name,
                i.level,
                si.valid_from
            FROM security_industry si
            JOIN industry i ON i.industry_id = si.industry_id
            JOIN industry_taxonomy t ON t.taxonomy_id = i.taxonomy_id
            JOIN security s ON s.security_id = si.security_id
            WHERE i.code = :industry_code
              AND t.code = :taxonomy
              AND si.valid_from <= :as_of
              AND (si.valid_to IS NULL OR si.valid_to > :as_of)
            ORDER BY s.symbol
            LIMIT :limit_fetch
            """
        )
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    stmt,
                    {
                        "industry_code": industry_code,
                        "taxonomy": taxonomy,
                        "as_of": as_of,
                        "limit_fetch": int(limit),
                    },
                )
                .mappings()
                .all()
            )
        df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
        if not df.is_empty() and "valid_from" in df.columns:
            assert_no_lookahead(df, as_of, "valid_from")
        return df

    def get_peers(
        self,
        symbol: str,
        *,
        as_of: date,
        n: int = 10,
        taxonomy: str = "sw_2021",
    ) -> pl.DataFrame:
        """Same-industry peers (excludes ``symbol``). Empty if industry unknown."""
        ind = self.get_industry([symbol], as_of=as_of, taxonomy=taxonomy)
        if ind.is_empty() or "industry_code" not in ind.columns:
            return pl.DataFrame()
        code = str(ind["industry_code"][0])
        members = self.get_industry_members(
            code, as_of=as_of, taxonomy=taxonomy, limit=max(n + 5, 20)
        )
        if members.is_empty():
            return pl.DataFrame()
        peers = members.filter(pl.col("symbol") != symbol).head(n)
        return peers
