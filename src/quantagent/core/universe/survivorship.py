"""Gate 4 survivorship check: a historical pool must contain later delistings."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.engine import Engine

from quantagent.shared.errors import QuantAgentError


class SurvivorshipBiasError(QuantAgentError):
    """Historical universe has no name that delists afterwards."""


class DelistRecord(BaseModel):
    symbol: str
    name: str
    list_date: date
    delist_date: date


class SurvivorshipCheck(BaseModel):
    universe: str
    as_of: date
    until: date
    n_universe: int
    symbols: list[str] = Field(default_factory=list)


class UniverseDelistSource(Protocol):
    def resolve_universe_symbols(self, *, as_of: date, name: str) -> list[str]: ...

    def get_delisted_between(self, start: date, end: date) -> list[str]: ...


def later_delisted_symbols(universe: list[str], delisted_after: list[str]) -> list[str]:
    """Sorted intersection. ``delisted_after`` already excludes the snapshot date."""
    later = set(delisted_after)
    return sorted(symbol for symbol in dict.fromkeys(universe) if symbol in later)


def check_universe_contains_delisted(
    repo: UniverseDelistSource,
    *,
    name: str,
    as_of: date,
    until: date,
) -> SurvivorshipCheck:
    """Require the snapshot on or before ``as_of`` to contain a later delisting.

    ``get_delisted_between`` is inclusive, so the window starts the day after
    ``as_of``. A name that delists on the snapshot date is already out of the pool.
    """
    if until <= as_of:
        raise QuantAgentError("survivorship until must be after as_of")
    universe = list(dict.fromkeys(repo.resolve_universe_symbols(as_of=as_of, name=name)))
    if not universe:
        raise SurvivorshipBiasError(
            f"universe {name!r} has no snapshot on or before {as_of.isoformat()}"
        )
    overlap = later_delisted_symbols(
        universe,
        repo.get_delisted_between(as_of + timedelta(days=1), until),
    )
    if not overlap:
        raise SurvivorshipBiasError(
            f"universe {name!r} as_of={as_of.isoformat()} contains no name "
            f"delisted by {until.isoformat()}"
        )
    return SurvivorshipCheck(
        universe=name,
        as_of=as_of,
        until=until,
        n_universe=len(universe),
        symbols=overlap,
    )


def former_members_without_delist_date(engine: Engine, *, universe: str) -> list[str]:
    """Historical members absent from the latest snapshot, with no ``delist_date``.

    Names that still have a bar on the latest snapshot date are still trading,
    so they are not candidates.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH snaps AS (
                    SELECT us.snapshot_date, s.security_id, s.symbol, s.delist_date
                    FROM universe_snapshot us
                    JOIN universe u ON u.universe_id = us.universe_id
                    JOIN security s ON s.security_id = us.security_id
                    WHERE u.code = :code
                ),
                latest AS (
                    SELECT MAX(snapshot_date) AS d FROM snaps
                ),
                former AS (
                    SELECT DISTINCT security_id, symbol
                    FROM snaps
                    WHERE delist_date IS NULL
                      AND symbol NOT IN (
                          SELECT symbol FROM snaps
                          WHERE snapshot_date = (SELECT d FROM latest)
                      )
                )
                SELECT f.symbol
                FROM former f
                LEFT JOIN LATERAL (
                    SELECT MAX(p.trade_date) AS last_px
                    FROM price_daily p
                    WHERE p.security_id = f.security_id
                ) px ON TRUE
                CROSS JOIN latest
                WHERE px.last_px IS NULL OR px.last_px < latest.d
                ORDER BY f.symbol
                """
            ),
            {"code": universe},
        ).fetchall()
    return [str(row[0]) for row in rows]


def apply_delist_records(engine: Engine, records: list[DelistRecord]) -> list[str]:
    """Write ``delist_date`` onto existing securities. Does not insert or delete rows.

    An existing different ``delist_date`` is a conflict and is left unchanged
    by raising, so a second source cannot silently rewrite history.
    """
    updated: list[str] = []
    with engine.begin() as conn:
        for record in records:
            if record.delist_date < record.list_date:
                raise QuantAgentError(
                    f"{record.symbol} delist_date is before list_date"
                )
            row = conn.execute(
                text(
                    """
                    SELECT security_id, delist_date
                    FROM security
                    WHERE symbol = :symbol
                    """
                ),
                {"symbol": record.symbol},
            ).one_or_none()
            if row is None:
                raise KeyError(f"Unknown symbol: {record.symbol}")
            existing = row.delist_date
            if existing is not None and existing != record.delist_date:
                raise QuantAgentError(
                    f"{record.symbol} delist_date conflict: "
                    f"stored={existing.isoformat()} incoming={record.delist_date.isoformat()}"
                )
            conn.execute(
                text(
                    """
                    UPDATE security
                    SET name = :name,
                        list_date = :list_date,
                        delist_date = :delist_date
                    WHERE security_id = :sid
                    """
                ),
                {
                    "sid": row.security_id,
                    "name": record.name,
                    "list_date": record.list_date,
                    "delist_date": record.delist_date,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO security_status_history
                        (security_id, valid_from, valid_to, name, status, is_st, source)
                    VALUES
                        (:sid, :list_date, :delist_date, :name, 'listed', FALSE, 'baostock')
                    ON CONFLICT (security_id, valid_from) DO UPDATE
                      SET valid_to = EXCLUDED.valid_to,
                          name = EXCLUDED.name,
                          status = EXCLUDED.status,
                          source = EXCLUDED.source
                    """
                ),
                {
                    "sid": row.security_id,
                    "list_date": record.list_date,
                    "delist_date": record.delist_date,
                    "name": record.name,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO security_status_history
                        (security_id, valid_from, valid_to, name, status, is_st, source)
                    VALUES
                        (:sid, :delist_date, NULL, :name, 'delisted', FALSE, 'baostock')
                    ON CONFLICT (security_id, valid_from) DO UPDATE
                      SET valid_to = EXCLUDED.valid_to,
                          name = EXCLUDED.name,
                          status = EXCLUDED.status,
                          source = EXCLUDED.source
                    """
                ),
                {
                    "sid": row.security_id,
                    "delist_date": record.delist_date,
                    "name": record.name,
                },
            )
            updated.append(record.symbol)
    if updated:
        prune_snapshots_on_or_after_delist(engine, symbols=updated)
    return updated


def prune_snapshots_on_or_after_delist(
    engine: Engine,
    *,
    universe: str | None = None,
    symbols: list[str] | None = None,
) -> list[str]:
    """Remove snapshot rows on or after ``delist_date`` and equal-weight those dates.

    ``seed_universe_snapshot`` already refuses names with ``delist_date <= as_of``.
    Rows written before the delist date was known are dropped here.
    """
    clauses = [
        "s.delist_date IS NOT NULL",
        "us.snapshot_date >= s.delist_date",
    ]
    params: dict[str, object] = {}
    if universe is not None:
        clauses.append("u.code = :code")
        params["code"] = universe
    if symbols is not None:
        clauses.append("s.symbol = ANY(:symbols)")
        params["symbols"] = symbols
    where = " AND ".join(clauses)
    stmt = text(
        f"""
        SELECT us.snapshot_date, s.symbol, us.universe_id, us.security_id
        FROM universe_snapshot us
        JOIN universe u ON u.universe_id = us.universe_id
        JOIN security s ON s.security_id = us.security_id
        WHERE {where}
        ORDER BY s.symbol, us.snapshot_date
        """
    )
    if symbols is not None:
        stmt = stmt.bindparams(bindparam("symbols", type_=ARRAY(TEXT())))
    removed: list[str] = []
    with engine.begin() as conn:
        rows = conn.execute(stmt, params).fetchall()
        if not rows:
            return []
        dates = {(int(row.universe_id), row.snapshot_date) for row in rows}
        for row in rows:
            conn.execute(
                text(
                    """
                    DELETE FROM universe_snapshot
                    WHERE universe_id = :uid
                      AND snapshot_date = :d
                      AND security_id = :sid
                    """
                ),
                {"uid": row.universe_id, "d": row.snapshot_date, "sid": row.security_id},
            )
            removed.append(str(row.symbol))
        for universe_id, snapshot_date in dates:
            conn.execute(
                text(
                    """
                    UPDATE universe_snapshot
                    SET weight = 1.0 / (
                        SELECT COUNT(*) FROM universe_snapshot
                        WHERE universe_id = :uid AND snapshot_date = :d
                    )
                    WHERE universe_id = :uid AND snapshot_date = :d
                    """
                ),
                {"uid": universe_id, "d": snapshot_date},
            )
    return removed
