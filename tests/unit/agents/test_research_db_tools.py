"""Unit tests for research DB tools + PIT extensions (mocked, no Postgres)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.agents.base import AgentContext
from quantagent.agents.tools import build_default_tool_registry
from quantagent.agents.tools.dispatch import ToolError
from quantagent.agents.tools.research_db import (
    DB_TOOL_NAMES,
    get_financials,
    get_macro_series,
    get_market_breadth,
    get_sector_prices,
    get_stock_prices,
)
from quantagent.core.repository.pit import PITRepository

CN_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(
        as_of=date(2026, 9, 12),
        market="CN",
        run_id="test-db-tools",
    )


def test_build_registry_includes_db_tools() -> None:
    reg = build_default_tool_registry(include_knowledge=False, include_db=True)
    names = set(reg.names())
    assert "get_stock_prices" in names
    assert "get_financials" in names
    assert "get_market_breadth" in names
    assert "search_knowledge" not in names
    for name in DB_TOOL_NAMES:
        assert name in names


def test_offline_registry_excludes_db() -> None:
    reg = build_default_tool_registry(include_knowledge=False, include_db=False)
    assert reg.names() == []


def test_get_stock_prices_uses_repo_and_as_of(ctx: AgentContext) -> None:
    repo = MagicMock(spec=PITRepository)
    repo.get_prices.return_value = pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 9, 12)],
            "close": [1800.0],
            "_as_of": [date(2026, 9, 12)],
        }
    )
    out = get_stock_prices("600519.SH", as_of=ctx.as_of, lookback_days=10, repo=repo)
    assert out["available"] is True
    assert out["symbol"] == "600519.SH"
    assert len(out["rows"]) == 1
    assert out["rows"][0]["close"] == 1800.0
    repo.get_prices.assert_called_once()
    kwargs = repo.get_prices.call_args.kwargs
    assert kwargs["as_of"] == ctx.as_of
    assert kwargs["end"] == ctx.as_of


def test_registry_injects_as_of_for_db_tool(ctx: AgentContext) -> None:
    repo = MagicMock(spec=PITRepository)
    repo.get_financials.return_value = pl.DataFrame()
    reg = build_default_tool_registry(
        include_knowledge=False, include_db=True, repo=repo
    )
    out = reg.call("get_financials", {"symbol": "600519.SH", "periods": 4}, ctx)
    assert out["available"] is True
    repo.get_financials.assert_called_once()
    assert repo.get_financials.call_args.kwargs["as_of"] == ctx.as_of

    with pytest.raises(ToolError, match="must not pass as_of"):
        reg.call(
            "get_financials",
            {"symbol": "600519.SH", "as_of": date(2099, 1, 1)},
            ctx,
        )


def test_macro_series_unavailable_stub(ctx: AgentContext) -> None:
    out = get_macro_series(["cpi"], as_of=ctx.as_of)
    assert out["available"] is False
    assert "macro" in out["reason"]


def test_market_breadth_empty_universe(ctx: AgentContext) -> None:
    repo = MagicMock(spec=PITRepository)
    repo.resolve_universe_symbols.return_value = []
    out = get_market_breadth(as_of=ctx.as_of, repo=repo)
    assert out["available"] is True
    assert out["n_names"] == 0
    assert out["today"] is None


def test_sector_prices_equal_weight_proxy(ctx: AgentContext) -> None:
    repo = MagicMock(spec=PITRepository)
    repo.get_industry_members.return_value = pl.DataFrame(
        {
            "symbol": ["AAA.SH", "BBB.SH"],
            "name": ["A", "B"],
            "industry_code": ["801010", "801010"],
        }
    )
    repo.get_prices.return_value = pl.DataFrame(
        {
            "symbol": ["AAA.SH", "AAA.SH", "BBB.SH", "BBB.SH"],
            "trade_date": [
                date(2026, 9, 10),
                date(2026, 9, 12),
                date(2026, 9, 10),
                date(2026, 9, 12),
            ],
            "close": [10.0, 11.0, 20.0, 22.0],
        }
    )
    out = get_sector_prices("801010", as_of=ctx.as_of, lookback_days=5, repo=repo)
    assert out["available"] is True
    assert out["proxy"] == "equal_weight_constituents"
    assert out["n_names"] == 2
    assert len(out["rows"]) == 2
    # Day1 = 1.0, Day2 = mean(1.1, 1.1) = 1.1
    last = out["rows"][-1]
    assert last["ew_index"] == pytest.approx(1.1)


def test_get_financials_tool_empty(ctx: AgentContext) -> None:
    repo = MagicMock(spec=PITRepository)
    repo.get_financials.return_value = pl.DataFrame()
    out = get_financials("600519.SH", as_of=ctx.as_of, repo=repo)
    assert out["rows"] == []


def _repo_mock() -> PITRepository:
    repo = PITRepository.__new__(PITRepository)
    repo._engine = MagicMock()
    return repo


def _connect_ctx(conn: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


def test_pit_get_valuation_asserts_no_lookahead(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_mock()
    conn = MagicMock()
    monkeypatch.setattr(
        repo,
        "_resolve_symbol_ids",
        lambda _c, _s: {"600519.SH": 1},
    )
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "security_id": 1,
            "trade_date": date(2026, 9, 10),
            "pe_ttm": 20.0,
            "pb": 5.0,
            "market_cap": 1e12,
            "circ_market_cap": 1e12,
            "pe_lyr": 21.0,
            "ps_ttm": 8.0,
            "dividend_yield": 0.02,
            "source": "test",
        }
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    df = repo.get_valuation(
        ["600519.SH"],
        as_of=date(2026, 9, 12),
        start=date(2026, 1, 1),
    )
    assert not df.is_empty()
    assert "symbol" in df.columns


def test_pit_get_news_rejects_future() -> None:
    repo = _repo_mock()
    conn = MagicMock()
    future = datetime(2099, 1, 1, 12, 0, tzinfo=CN_TZ)
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "news_id": 1,
            "source": "cls",
            "source_id": "x",
            "url": None,
            "title": "future",
            "body_excerpt": "",
            "published_at": future,
            "related_symbol": None,
            "announce_type": None,
        }
    ]
    repo._engine.connect.return_value = _connect_ctx(conn)
    from quantagent.shared.errors import LookaheadError

    with pytest.raises(LookaheadError):
        repo.get_news(as_of=date(2026, 9, 12), start=date(2026, 9, 1), limit=5)
