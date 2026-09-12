"""Append-only Postgres store for shadow portfolio daily records."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from quantagent.shared.config import get_settings

logger = logging.getLogger(__name__)


class ShadowDayStore:
    """Optional Postgres append-only store for ``ShadowDayRecord`` rows."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def try_connect(cls) -> ShadowDayStore | None:
        """Return a store when ``shadow_day`` table is reachable; else ``None``."""
        try:
            engine = create_engine(get_settings().database_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM shadow_day LIMIT 0"))
            return cls(engine)
        except SQLAlchemyError as exc:
            logger.debug("shadow_day DB store unavailable: %s", exc)
            return None

    def append(self, record: BaseModel) -> None:
        payload = record.model_dump(mode="json")
        stmt = text(
            """
            INSERT INTO shadow_day (
                portfolio, as_of, run_id, nav, cash, ret_1d, ret_cum,
                max_drawdown, n_positions, weights, unfilled, notes
            ) VALUES (
                :portfolio, :as_of, :run_id, :nav, :cash, :ret_1d, :ret_cum,
                :max_drawdown, :n_positions, :weights, :unfilled, :notes
            )
            ON CONFLICT (portfolio, as_of, run_id) DO NOTHING
            """
        )
        with self._engine.begin() as conn:
            conn.execute(
                stmt,
                {
                    "portfolio": payload["portfolio"],
                    "as_of": payload["as_of"],
                    "run_id": payload["run_id"],
                    "nav": payload["nav"],
                    "cash": payload["cash"],
                    "ret_1d": payload["ret_1d"],
                    "ret_cum": payload["ret_cum"],
                    "max_drawdown": payload["max_drawdown"],
                    "n_positions": payload["n_positions"],
                    "weights": json.dumps(payload["weights"]),
                    "unfilled": json.dumps(payload["unfilled"]),
                    "notes": json.dumps(payload["notes"]),
                },
            )
