"""Research Agent DB tools — all historical reads via ``PITRepository``.

Agent-facing signatures omit ``as_of``; ``ToolRegistry`` injects it.
Unavailable domains (macro / northbound / money-flow tables not migrated)
return structured empty payloads with ``available=False``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import polars as pl

from quantagent.agents.tools.dispatch import require_as_of
from quantagent.core.repository.pit import PITRepository

DEFAULT_UNIVERSE = "mvp_cn_50"
DEFAULT_INDEX = "000300.SH"
MAX_PRICE_ROWS = 120
MAX_FUND_ROWS = 16
MAX_NEWS_ROWS = 30
MAX_EVENT_ROWS = 40
MAX_CONSTITUENTS = 80


def _repo(repo: PITRepository | None) -> PITRepository:
    return repo if repo is not None else PITRepository()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, float | int | str | bool):
        return value
    return str(value)


def _df_records(df: pl.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    if df.is_empty():
        return []
    cols = [c for c in df.columns if not c.startswith("_")]
    slim = df.select(cols).head(limit)
    return [_jsonable(dict(row)) for row in slim.to_dicts()]


def _lookback_start(as_of: date, lookback_days: int) -> date:
    days = max(1, int(lookback_days))
    return as_of - timedelta(days=days)


def _unavailable(name: str, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "tool": name,
        "reason": reason,
        "rows": [],
    }


# ── prices ──────────────────────────────────────────────────────────


def get_stock_prices(
    symbol: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 60,
    adjust: str = "qfq",
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    start = _lookback_start(day, lookback_days)
    df = _repo(repo).get_prices([symbol], as_of=day, start=start, end=day, adjust=adjust)
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "adjust": adjust,
        "rows": _df_records(df, limit=MAX_PRICE_ROWS),
    }


def get_index_prices(
    index_codes: list[str] | None = None,
    *,
    as_of: date | None = None,
    lookback_days: int = 60,
    adjust: str = "qfq",
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    codes = list(index_codes) if index_codes else [DEFAULT_INDEX]
    start = _lookback_start(day, lookback_days)
    df = _repo(repo).get_prices(codes, as_of=day, start=start, end=day, adjust=adjust)
    return {
        "available": True,
        "index_codes": codes,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "rows": _df_records(df, limit=MAX_PRICE_ROWS * max(len(codes), 1)),
    }


# ── fundamentals ────────────────────────────────────────────────────


def get_financials(
    symbol: str,
    *,
    as_of: date | None = None,
    periods: int = 8,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    df = _repo(repo).get_financials([symbol], as_of=day, periods=periods)
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "periods": periods,
        "rows": _df_records(df, limit=MAX_FUND_ROWS),
    }


def get_financial_indicators(
    symbol: str,
    *,
    as_of: date | None = None,
    periods: int = 8,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    df = _repo(repo).get_financial_indicators([symbol], as_of=day, periods=periods)
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "periods": periods,
        "rows": _df_records(df, limit=MAX_FUND_ROWS),
    }


def get_valuation(
    symbol: str,
    *,
    as_of: date | None = None,
    lookback_years: int = 3,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    years = max(1, int(lookback_years))
    start = day - timedelta(days=365 * years)
    df = _repo(repo).get_valuation([symbol], as_of=day, start=start, end=day)
    # Keep latest + sparse history: last 60 points max
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "rows": _df_records(df, limit=MAX_PRICE_ROWS),
        "latest": _df_records(df.sort("trade_date") if not df.is_empty() else df, limit=1),
    }


# ── news / events ───────────────────────────────────────────────────


def get_stock_news(
    symbol: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 14,
    limit: int = 20,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    start = _lookback_start(day, lookback_days)
    rows = _repo(repo).get_news(
        as_of=day,
        start=start,
        limit=min(limit, MAX_NEWS_ROWS),
        related_symbol=symbol,
    )
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "rows": [_jsonable(r) for r in rows],
    }


def get_announcements(
    symbol: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 30,
    limit: int = 20,
    types: list[str] | None = None,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    start = _lookback_start(day, lookback_days)
    rows = _repo(repo).get_news(
        as_of=day,
        start=start,
        limit=min(limit * 2, MAX_NEWS_ROWS * 2),
        sources=["em_announce"],
        related_symbol=symbol,
    )
    if types:
        wanted = {t.lower() for t in types}
        rows = [
            r
            for r in rows
            if str(r.get("announce_type") or "").lower() in wanted
            or any(w in str(r.get("title") or "").lower() for w in wanted)
        ]
    rows = rows[: min(limit, MAX_NEWS_ROWS)]
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "rows": [_jsonable(r) for r in rows],
    }


def get_policy_news(
    *,
    as_of: date | None = None,
    lookback_days: int = 14,
    limit: int = 20,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    start = _lookback_start(day, lookback_days)
    r = _repo(repo)
    events = r.get_events(
        as_of=day,
        start=start,
        limit=min(limit, MAX_EVENT_ROWS),
        event_types=["policy", "regulation"],
    )
    news = r.get_news(
        as_of=day,
        start=start,
        limit=min(limit, MAX_NEWS_ROWS),
        sources=["cls", "em"],
    )
    # Prefer event hits; fall back to keyword-ish flash titles
    if not events:
        keys = ("政策", "国务院", "央行", "证监会", "监管", "降准", "降息")
        news = [n for n in news if any(k in str(n.get("title") or "") for k in keys)]
    return {
        "available": True,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "events": [_jsonable(e) for e in events],
        "news": [_jsonable(n) for n in news[:limit]],
    }


def get_stock_events(
    symbol: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 14,
    limit: int = 20,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    start = _lookback_start(day, lookback_days)
    rows = _repo(repo).get_events(
        as_of=day,
        start=start,
        limit=min(limit, MAX_EVENT_ROWS),
        symbol=symbol,
    )
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "rows": [_jsonable(r) for r in rows],
    }


# ── sector / peers ──────────────────────────────────────────────────


def get_sector_constituents(
    sector_code: str,
    *,
    as_of: date | None = None,
    taxonomy: str = "sw_2021",
    limit: int = 50,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    df = _repo(repo).get_industry_members(
        sector_code,
        as_of=day,
        taxonomy=taxonomy,
        limit=min(limit, MAX_CONSTITUENTS),
    )
    return {
        "available": True,
        "sector_code": sector_code,
        "taxonomy": taxonomy,
        "as_of": day.isoformat(),
        "rows": _df_records(df, limit=MAX_CONSTITUENTS),
    }


def get_sector_prices(
    sector_code: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 60,
    taxonomy: str = "sw_2021",
    max_names: int = 30,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    """Equal-weight proxy return of industry members (no dedicated sector index)."""
    day = require_as_of(as_of)
    r = _repo(repo)
    members = r.get_industry_members(
        sector_code, as_of=day, taxonomy=taxonomy, limit=max_names
    )
    if members.is_empty():
        return {
            "available": True,
            "sector_code": sector_code,
            "as_of": day.isoformat(),
            "proxy": "equal_weight_constituents",
            "n_names": 0,
            "rows": [],
        }
    symbols = [str(s) for s in members["symbol"].to_list()][:max_names]
    start = _lookback_start(day, lookback_days)
    prices = r.get_prices(symbols, as_of=day, start=start, end=day, adjust="qfq")
    if prices.is_empty() or "close" not in prices.columns:
        return {
            "available": True,
            "sector_code": sector_code,
            "as_of": day.isoformat(),
            "proxy": "equal_weight_constituents",
            "n_names": len(symbols),
            "rows": [],
        }
    # Equal-weight index: mean of normalized closes per day
    base = (
        prices.sort(["symbol", "trade_date"])
        .with_columns(
            (pl.col("close") / pl.col("close").first().over("symbol")).alias("norm")
        )
        .group_by("trade_date")
        .agg(pl.col("norm").mean().alias("ew_index"), pl.len().alias("n"))
        .sort("trade_date")
    )
    return {
        "available": True,
        "sector_code": sector_code,
        "as_of": day.isoformat(),
        "proxy": "equal_weight_constituents",
        "n_names": len(symbols),
        "rows": _df_records(base, limit=MAX_PRICE_ROWS),
    }


def get_sector_news(
    sector_code: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 14,
    limit: int = 20,
    taxonomy: str = "sw_2021",
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    r = _repo(repo)
    members = r.get_industry_members(
        sector_code, as_of=day, taxonomy=taxonomy, limit=40
    )
    symbols = set(str(s) for s in members["symbol"].to_list()) if not members.is_empty() else set()
    start = _lookback_start(day, lookback_days)
    events = r.get_events(as_of=day, start=start, limit=MAX_EVENT_ROWS * 2)
    filtered: list[dict[str, object]] = []
    for e in events:
        raw = e.get("symbols")
        ev_syms = {str(x) for x in raw} if isinstance(raw, (list, tuple)) else set()
        if symbols & ev_syms:
            filtered.append(e)
        if len(filtered) >= min(limit, MAX_EVENT_ROWS):
            break
    return {
        "available": True,
        "sector_code": sector_code,
        "as_of": day.isoformat(),
        "start": start.isoformat(),
        "rows": [_jsonable(e) for e in filtered],
    }


def get_peers(
    symbol: str,
    *,
    as_of: date | None = None,
    n: int = 10,
    taxonomy: str = "sw_2021",
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    df = _repo(repo).get_peers(symbol, as_of=day, n=n, taxonomy=taxonomy)
    return {
        "available": True,
        "symbol": symbol,
        "as_of": day.isoformat(),
        "n": n,
        "rows": _df_records(df, limit=n),
    }


# ── market breadth ──────────────────────────────────────────────────


def get_market_breadth(
    *,
    as_of: date | None = None,
    lookback_days: int = 20,
    universe: str = DEFAULT_UNIVERSE,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    day = require_as_of(as_of)
    r = _repo(repo)
    symbols = r.resolve_universe_symbols(as_of=day, name=universe)
    if not symbols:
        return {
            "available": True,
            "as_of": day.isoformat(),
            "universe": universe,
            "n_names": 0,
            "today": None,
            "history": [],
            "note": "universe empty or missing snapshot",
        }
    start = _lookback_start(day, lookback_days + 5)
    prices = r.get_prices(symbols, as_of=day, start=start, end=day, adjust="qfq")
    if prices.is_empty():
        return {
            "available": True,
            "as_of": day.isoformat(),
            "universe": universe,
            "n_names": len(symbols),
            "today": None,
            "history": [],
        }

    hist: list[dict[str, Any]] = []
    dates = (
        prices.filter(pl.col("trade_date") <= day)["trade_date"]
        .unique()
        .sort()
        .tail(lookback_days)
        .to_list()
    )
    for td in dates:
        g = prices.filter(pl.col("trade_date") == td)
        if "prev_close" in g.columns:
            rets = g.select((pl.col("close") / pl.col("prev_close") - 1.0).alias("r")).drop_nulls()
        else:
            continue
        n_up = int(rets.filter(pl.col("r") > 1e-12).height)
        n_down = int(rets.filter(pl.col("r") < -1e-12).height)
        n_flat = int(rets.height) - n_up - n_down
        amount = float(g["amount"].sum()) if "amount" in g.columns else None
        hist.append(
            {
                "trade_date": td.isoformat() if isinstance(td, date) else str(td),
                "n_up": n_up,
                "n_down": n_down,
                "n_flat": n_flat,
                "total_amount": amount,
            }
        )
    today = hist[-1] if hist else None
    return {
        "available": True,
        "as_of": day.isoformat(),
        "universe": universe,
        "n_names": len(symbols),
        "today": today,
        "history": hist,
    }


# ── not-yet-migrated domains ────────────────────────────────────────


def get_macro_series(
    series_ids: list[str] | None = None,
    *,
    as_of: date | None = None,
    lookback_months: int = 12,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    _ = (series_ids, lookback_months, repo)
    require_as_of(as_of)
    return _unavailable(
        "get_macro_series",
        "macro_series / macro_observation tables not migrated yet",
    )


def get_northbound_flow(
    *,
    as_of: date | None = None,
    lookback_days: int = 20,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    _ = (lookback_days, repo)
    require_as_of(as_of)
    return _unavailable(
        "get_northbound_flow",
        "northbound / capital-flow tables not migrated yet",
    )


def get_money_flow(
    symbol: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 20,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    _ = (symbol, lookback_days, repo)
    require_as_of(as_of)
    return _unavailable(
        "get_money_flow",
        "money_flow table not migrated yet",
    )


def get_sector_flow(
    sector_code: str,
    *,
    as_of: date | None = None,
    lookback_days: int = 20,
    repo: PITRepository | None = None,
) -> dict[str, Any]:
    _ = (sector_code, lookback_days, repo)
    require_as_of(as_of)
    return _unavailable(
        "get_sector_flow",
        "sector money-flow table not migrated yet",
    )


DB_TOOL_NAMES: tuple[str, ...] = (
    "get_stock_prices",
    "get_index_prices",
    "get_financials",
    "get_financial_indicators",
    "get_valuation",
    "get_stock_news",
    "get_announcements",
    "get_policy_news",
    "get_stock_events",
    "get_sector_constituents",
    "get_sector_prices",
    "get_sector_news",
    "get_peers",
    "get_market_breadth",
    "get_macro_series",
    "get_northbound_flow",
    "get_money_flow",
    "get_sector_flow",
)


def register_db_tools(
    registry: Any,
    *,
    repo: PITRepository | None = None,
) -> None:
    """Bind DB tools onto a ``ToolRegistry`` (optional shared ``PITRepository``)."""
    from functools import partial

    mapping: dict[str, Any] = {
        "get_stock_prices": get_stock_prices,
        "get_index_prices": get_index_prices,
        "get_financials": get_financials,
        "get_financial_indicators": get_financial_indicators,
        "get_valuation": get_valuation,
        "get_stock_news": get_stock_news,
        "get_announcements": get_announcements,
        "get_policy_news": get_policy_news,
        "get_stock_events": get_stock_events,
        "get_sector_constituents": get_sector_constituents,
        "get_sector_prices": get_sector_prices,
        "get_sector_news": get_sector_news,
        "get_peers": get_peers,
        "get_market_breadth": get_market_breadth,
        "get_macro_series": get_macro_series,
        "get_northbound_flow": get_northbound_flow,
        "get_money_flow": get_money_flow,
        "get_sector_flow": get_sector_flow,
    }
    for name, fn in mapping.items():
        if repo is not None:
            registry.register(name, partial(fn, repo=repo))
        else:
            registry.register(name, fn)
