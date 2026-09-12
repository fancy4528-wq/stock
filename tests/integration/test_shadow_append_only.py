"""Integration: shadow_day table is append-only at DB level."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from quantagent.core.repository.shadow_day import ShadowDayStore
from quantagent.evaluation.shadow.types import ShadowDayRecord

pytestmark = pytest.mark.integration


def _ensure_shadow_day(engine: Engine) -> None:
    """Apply 0004 DDL when integration DB has not been migrated yet."""
    from pathlib import Path

    ddl = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "quantagent"
        / "core"
        / "repository"
        / "sql"
        / "005_append_only.sql"
    ).read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(ddl))


def test_shadow_day_trigger_blocks_update(clean_pit_tables: Engine) -> None:
    engine = clean_pit_tables
    _ensure_shadow_day(engine)
    store = ShadowDayStore(engine)
    rec = ShadowDayRecord(
        portfolio="shadow_baseline",
        as_of=date(2026, 9, 1),
        run_id="test-run",
        strategy_version="v1",
        nav=1_000_000.0,
        cash=100_000.0,
        ret_1d=0.0,
        ret_cum=0.0,
        max_drawdown=0.0,
        n_positions=5,
    )
    store.append(rec)

    with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(
            text(
                """
                UPDATE shadow_day SET nav = 0
                WHERE portfolio = 'shadow_baseline' AND as_of = '2026-09-01'
                """
            )
        )

    with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(
            text(
                """
                DELETE FROM shadow_day
                WHERE portfolio = 'shadow_baseline' AND as_of = '2026-09-01'
                """
            )
        )
