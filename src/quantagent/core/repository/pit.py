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

    def get_security_names(self, symbols: list[str]) -> dict[str, str]:
        """Return ``symbol -> name`` for known securities (empty dict if none)."""
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

    def latest_trade_date(
        self,
        symbols: list[str],
        *,
        on_or_before: date | None = None,
    ) -> date | None:
        """Max ``trade_date`` present in ``price_daily`` for the given symbols."""
        if not symbols:
            return None
        with self._engine.connect() as conn:
            sec_ids = self._resolve_ids(conn, symbols)
            if not sec_ids:
                return None
            if on_or_before is None:
                stmt = text(
                    """
                    SELECT max(trade_date) AS d
                    FROM price_daily
                    WHERE security_id = ANY(:ids)
                    """
                ).bindparams(bindparam("ids", type_=ARRAY(BIGINT())))
                row = conn.execute(stmt, {"ids": sec_ids}).mappings().one()
            else:
                stmt = text(
                    """
                    SELECT max(trade_date) AS d
                    FROM price_daily
                    WHERE security_id = ANY(:ids)
                      AND trade_date <= :end
                    """
                ).bindparams(bindparam("ids", type_=ARRAY(BIGINT())))
                row = conn.execute(stmt, {"ids": sec_ids, "end": on_or_before}).mappings().one()
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
        return pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
