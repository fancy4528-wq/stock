"""Integration fixtures — require local Docker Postgres."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from quantagent.shared.config import get_settings


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: needs running Postgres")


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    get_settings.cache_clear()
    url = get_settings().database_url
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not available: {exc}")
    return engine


@pytest.fixture
def clean_pit_tables(pg_engine: Engine) -> Engine:
    """Truncate P0 tables between tests (FK-safe order)."""
    tables = [
        "valuation_daily",
        "financial_indicator",
        "financial_statement",
        "adjust_factor",
        "price_daily",
        "universe_snapshot",
        "security_industry",
        "industry",
        "industry_taxonomy",
        "security_status_history",
        "universe",
        "security",
        "trading_calendar",
    ]
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    return pg_engine
