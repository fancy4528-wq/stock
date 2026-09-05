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

    def _resolve_ids(self, conn: Connection, symbols: list[str]) -> list[int]:
        if not symbols:
            return []
        stmt = text(
            "SELECT security_id, symbol FROM security WHERE symbol = ANY(:symbols)"
        ).bindparams(bindparam("symbols", type_=ARRAY(TEXT())))
        result = conn.execute(stmt, {"symbols": symbols})
        by_symbol = {row.symbol: int(row.security_id) for row in result}
        missing = [s for s in symbols if s not in by_symbol]
        if missing:
            raise KeyError(f"Unknown symbols: {missing}")
        return [by_symbol[s] for s in symbols]

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
            sec_ids = self._resolve_ids(conn, symbols)
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
            df = df.with_columns(pl.lit(as_of).alias("_as_of"))
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
            sec_ids = self._resolve_ids(conn, symbols)
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
        return pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()

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
        return pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
