"""Unit tests for live ResearchFacts builder + DB-tool-aware Agents."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import polars as pl
import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.fixtures import sample_research_facts
from quantagent.agents.macro.agent import MacroAgent
from quantagent.agents.orchestrator import Orchestrator
from quantagent.agents.stock.agent import StockAgent, _health_from_rows
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.facts_builder import build_research_facts
from quantagent.agents.tools.research_facts import StockSeed
from quantagent.core.repository.pit import PITRepository
from quantagent.shared.errors import DataError


def test_build_research_facts_from_mocked_pit() -> None:
    repo = MagicMock(spec=PITRepository)
    repo.resolve_universe_symbols.return_value = ["AAA.SH", "BBB.SH"]
    repo.latest_trade_date.return_value = date(2026, 9, 12)
    repo.get_security_names.return_value = {"AAA.SH": "甲", "BBB.SH": "乙"}
    prices = pl.DataFrame(
        {
            "symbol": ["AAA.SH"] * 3 + ["BBB.SH"] * 3,
            "trade_date": [
                date(2026, 9, 10),
                date(2026, 9, 11),
                date(2026, 9, 12),
            ]
            * 2,
            "close": [10.0, 10.5, 11.0, 20.0, 19.5, 19.0],
            "prev_close": [9.8, 10.0, 10.5, 20.2, 20.0, 19.5],
            "amount": [1e8, 1e8, 1e8, 1e8, 1e8, 1e8],
        }
    )
    index = pl.DataFrame(
        {
            "symbol": ["000300.SH", "000300.SH"],
            "trade_date": [date(2026, 9, 11), date(2026, 9, 12)],
            "close": [4000.0, 4040.0],
        }
    )

    def _get_prices(symbols, **kwargs):  # noqa: ANN001
        if symbols == ["000300.SH"]:
            return index
        return prices

    repo.get_prices.side_effect = _get_prices
    repo.get_industry.return_value = pl.DataFrame(
        {
            "symbol": ["AAA.SH", "BBB.SH"],
            "industry_code": ["801010", "801010"],
            "industry_name": ["农林牧渔", "农林牧渔"],
            "level": [1, 1],
        }
    )
    repo.get_news.return_value = [{"news_id": 1}]
    repo.get_events.return_value = [{"event_id": 1}, {"event_id": 2}]

    facts = build_research_facts(as_of=date(2026, 9, 12), repo=repo)
    assert facts.as_of == date(2026, 9, 12)
    assert facts.index_return_1d == pytest.approx(0.01)
    assert facts.n_up + facts.n_down >= 1
    assert len(facts.industries) == 1
    assert facts.industries[0].code == "801010"
    assert facts.news_count == 1
    assert facts.events_count == 2
    assert facts.stocks


def test_build_research_facts_empty_universe() -> None:
    repo = MagicMock(spec=PITRepository)
    repo.resolve_universe_symbols.return_value = []
    with pytest.raises(DataError, match="empty"):
        build_research_facts(as_of=date(2026, 9, 12), repo=repo)


@pytest.mark.asyncio
async def test_macro_uses_breadth_and_policy_tools() -> None:
    facts = sample_research_facts(date(2026, 9, 12))
    ctx = AgentContext(as_of=facts.as_of, market="CN", run_id="t")
    reg = ToolRegistry()

    def breadth(*, lookback_days: int = 20, as_of: date | None = None):  # noqa: ARG001
        return {
            "available": True,
            "today": {"n_up": 2500, "n_down": 1000, "n_flat": 0},
            "history": [],
        }

    def policy(*, lookback_days: int = 14, limit: int = 10, as_of: date | None = None):  # noqa: ARG001
        return {"available": True, "events": [{"event_id": 1}] * 3, "news": []}

    def index_prices(*, index_codes=None, lookback_days=5, as_of=None, **_):  # noqa: ANN001
        return {
            "available": True,
            "rows": [
                {"close": 100.0, "trade_date": "2026-09-11"},
                {"close": 102.0, "trade_date": "2026-09-12"},
            ],
        }

    reg.register("get_market_breadth", breadth)
    reg.register("get_policy_news", policy)
    reg.register("get_index_prices", index_prices)

    view = await MacroAgent(facts, tools=reg).run(ctx)
    assert view.regime == "risk_on"  # breadth 2500-1000 and +2% index
    assert any(e.evidence_id == "ev-macro-policy" for e in view.evidence)
    assert "政策" in view.policy.note or "3" in view.policy.note


@pytest.mark.asyncio
async def test_stock_uses_financial_tools() -> None:
    seed = StockSeed(
        symbol="600519.SH",
        name="茅台",
        sector_code="801120",
        ret_20d=0.04,
        preliminary_score=0.6,
    )
    ctx = AgentContext(as_of=date(2026, 9, 12), market="CN", run_id="t")
    reg = ToolRegistry()

    def financials(*, symbol: str, periods: int = 8, as_of: date | None = None):  # noqa: ARG001
        return {
            "available": True,
            "rows": [
                {"revenue": 110.0, "period_end": "2026-06-30"},
                {"revenue": 100.0, "period_end": "2026-03-31"},
            ],
        }

    def indicators(*, symbol: str, periods: int = 8, as_of: date | None = None):  # noqa: ARG001
        return {
            "available": True,
            "rows": [
                {
                    "revenue_yoy": 0.12,
                    "gross_margin": 0.9,
                    "debt_to_asset": 0.2,
                    "ocf_to_profit": 1.1,
                },
                {"gross_margin": 0.88},
            ],
        }

    def valuation(*, symbol: str, lookback_years: int = 3, as_of: date | None = None):  # noqa: ARG001
        return {"available": True, "latest": [{"pe_ttm": 25.0, "pb": 8.0}], "rows": []}

    def events(*, symbol: str, lookback_days: int = 14, limit: int = 10, as_of=None):  # noqa: ARG001
        return {"available": True, "rows": [{"event_id": 9, "summary": "回购"}]}

    reg.register("get_financials", financials)
    reg.register("get_financial_indicators", indicators)
    reg.register("get_valuation", valuation)
    reg.register("get_stock_events", events)

    view = await StockAgent(seed, tools=reg).run(ctx)
    assert view.financial_health.revenue_trend in {"growing", "accelerating"}
    assert view.financial_health.cash_conversion == "strong"
    assert view.financial_health.leverage == "low"
    assert any(e.evidence_id == "ev-stock-fin" for e in view.evidence)
    assert "财务" in view.thesis


def test_health_from_rows_empty() -> None:
    h = _health_from_rows([], [])
    assert h.revenue_trend == "flat"
    assert "未读取" in h.notes


@pytest.mark.asyncio
async def test_orchestrator_with_db_tool_registry() -> None:
    facts = sample_research_facts(date(2026, 9, 12))
    reg = ToolRegistry()

    def unavailable(**_kwargs):  # noqa: ANN001
        return {"available": False, "reason": "stub", "rows": []}

    for name in (
        "get_market_breadth",
        "get_index_prices",
        "get_policy_news",
        "get_macro_series",
        "get_financials",
        "get_financial_indicators",
        "get_valuation",
        "get_stock_events",
        "get_sector_news",
        "get_sector_prices",
    ):
        reg.register(name, unavailable)

    orch = Orchestrator(tools=reg, max_stocks=5, max_concurrency=3)
    result = await orch.run_daily(facts.as_of, facts.market, facts)
    assert not result.aborted
    assert result.brief is not None
    assert result.brief.regime in {"risk_on", "risk_off", "neutral", "transition"}
