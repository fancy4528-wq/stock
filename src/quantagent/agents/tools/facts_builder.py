"""Build ``ResearchFacts`` from ``PITRepository`` for live research runs."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from quantagent.agents.tools.research_facts import (
    CandidateSeed,
    ResearchFacts,
    SectorSeed,
    StockSeed,
)
from quantagent.core.repository.pit import PITRepository
from quantagent.shared.errors import DataError

DEFAULT_UNIVERSE = "mvp_cn_50"
DEFAULT_INDEX = "000300.SH"
DEFAULT_TAXONOMY = "sw_2021"


def _symbol_ret(prices: pl.DataFrame, symbol: str, lookback: int) -> float:
    hist = prices.filter(pl.col("symbol") == symbol).sort("trade_date")
    if hist.height <= lookback:
        return 0.0
    c0 = float(hist["close"][-(lookback + 1)])
    c1 = float(hist["close"][-1])
    return (c1 / c0 - 1.0) if c0 else 0.0


def _index_return_1d(index_prices: pl.DataFrame, *, as_of: date) -> float:
    idx = index_prices.filter(pl.col("trade_date") <= as_of).sort("trade_date")
    if idx.height < 2:
        return 0.0
    c0 = float(idx["close"][-2])
    c1 = float(idx["close"][-1])
    return (c1 / c0 - 1.0) if c0 else 0.0


def _breadth(day: pl.DataFrame) -> tuple[int, int, float]:
    if day.is_empty():
        return 0, 0, 0.0
    if "prev_close" in day.columns:
        rets = day.select((pl.col("close") / pl.col("prev_close") - 1.0).alias("r")).drop_nulls()
    else:
        return 0, 0, 0.0
    n_up = int(rets.filter(pl.col("r") > 1e-12).height)
    n_down = int(rets.filter(pl.col("r") < -1e-12).height)
    amount = float(day["amount"].sum()) if "amount" in day.columns else 0.0
    return n_up, n_down, amount


def build_research_facts(
    *,
    as_of: date | None = None,
    market: str = "CN",
    universe: str = DEFAULT_UNIVERSE,
    index_symbol: str = DEFAULT_INDEX,
    taxonomy: str = DEFAULT_TAXONOMY,
    lookback_days: int = 45,
    max_industries: int = 12,
    candidates_per_industry: int = 5,
    max_stocks: int = 40,
    repo: PITRepository | None = None,
) -> ResearchFacts:
    """Assemble Stage-4a seeds from PIT prices + industry membership.

    Themes are left empty until a concept/theme membership table exists.
    """
    r = repo or PITRepository()
    probe = as_of or date.today()
    symbols = r.resolve_universe_symbols(as_of=probe, name=universe)
    if not symbols:
        raise DataError(
            f"universe {universe!r} empty as_of {probe}; seed-universe first"
        )

    latest = r.latest_trade_date(symbols + [index_symbol], as_of=probe)
    if latest is None:
        raise DataError("no price_daily rows for universe/index; ingest prices first")
    day = latest

    start = day - timedelta(days=lookback_days)
    names = r.get_security_names(symbols, as_of=day)
    uni_prices = r.get_prices(symbols, as_of=day, start=start, end=day, adjust="qfq")
    if uni_prices.is_empty():
        raise DataError(f"no universe prices between {start} and {day}")

    # Align as_of to a session that actually has bars
    day_panel = uni_prices.filter(pl.col("trade_date") == day)
    if day_panel.is_empty():
        max_td = uni_prices["trade_date"].max()
        if max_td is None:
            raise DataError("universe price panel has no trade_date")
        day = max_td if isinstance(max_td, date) else date.fromisoformat(str(max_td))
        day_panel = uni_prices.filter(pl.col("trade_date") == day)

    index_prices = r.get_prices(
        [index_symbol], as_of=day, start=start, end=day, adjust="qfq"
    )
    index_ret = _index_return_1d(index_prices, as_of=day)
    n_up, n_down, total_amount = _breadth(day_panel)

    industry = r.get_industry(symbols, as_of=day, taxonomy=taxonomy)
    industries = _build_industry_seeds(
        uni_prices,
        industry,
        names=names,
        as_of=day,
        max_industries=max_industries,
        candidates_per_industry=candidates_per_industry,
    )

    stocks = _build_stock_seeds(
        uni_prices,
        industry,
        names=names,
        as_of=day,
        limit=max_stocks,
    )

    news_count = 0
    events_count = 0
    try:
        news_count = len(
            r.get_news(as_of=day, start=day - timedelta(days=1), limit=50)
        )
        events_count = len(
            r.get_events(as_of=day, start=day - timedelta(days=1), limit=50)
        )
    except Exception:  # noqa: BLE001 — soft-fail optional counts
        pass

    return ResearchFacts(
        as_of=day,
        market=market,
        index_return_1d=index_ret,
        n_up=n_up,
        n_down=n_down,
        total_amount=total_amount,
        industries=industries,
        themes=[],
        stocks=stocks,
        macro_note=(
            f"live PIT facts universe={universe} index={index_symbol} "
            f"ret_1d={index_ret:+.2%} breadth={n_up}:{n_down}"
        ),
        news_count=news_count,
        events_count=events_count,
    )


def _build_industry_seeds(
    prices: pl.DataFrame,
    industry: pl.DataFrame,
    *,
    names: dict[str, str],
    as_of: date,
    max_industries: int,
    candidates_per_industry: int,
) -> list[SectorSeed]:
    if industry.is_empty() or "industry_code" not in industry.columns:
        return []

    ind = industry
    if "level" in ind.columns:
        lvl1 = ind.filter(pl.col("level") == 1)
        if not lvl1.is_empty():
            ind = lvl1

    code_name = (
        ind.select(["symbol", "industry_code", "industry_name"])
        .unique(subset=["symbol"])
    )
    day = prices.filter(pl.col("trade_date") == as_of)
    if day.is_empty():
        return []
    joined = day.join(code_name, on="symbol", how="inner")

    seeds: list[SectorSeed] = []
    for (code, iname), g in joined.group_by(["industry_code", "industry_name"]):
        syms = [str(s) for s in g["symbol"].to_list()]
        if not syms:
            continue
        r1 = sum(_symbol_ret(prices, s, 1) for s in syms) / len(syms)
        r20 = sum(_symbol_ret(prices, s, 20) for s in syms) / len(syms)
        ranked = sorted(
            syms,
            key=lambda s: _symbol_ret(prices, s, 20),
            reverse=True,
        )
        candidates = [
            CandidateSeed(
                symbol=s,
                name=names.get(s, s),
                role="constituent",
                preliminary_score=max(0.0, min(1.0, 0.5 + _symbol_ret(prices, s, 20))),
            )
            for s in ranked[:candidates_per_industry]
        ]
        seeds.append(
            SectorSeed(
                code=str(code),
                name=str(iname),
                ret_1d=r1,
                ret_20d=r20,
                candidates=candidates,
            )
        )

    seeds.sort(key=lambda s: (abs(s.ret_20d), s.ret_1d), reverse=True)
    return seeds[: max(0, max_industries)]


def _build_stock_seeds(
    prices: pl.DataFrame,
    industry: pl.DataFrame,
    *,
    names: dict[str, str],
    as_of: date,
    limit: int,
) -> list[StockSeed]:
    day = prices.filter(pl.col("trade_date") == as_of)
    if day.is_empty():
        return []
    sector_by_sym: dict[str, str] = {}
    if not industry.is_empty() and "industry_code" in industry.columns:
        for row in industry.select(["symbol", "industry_code"]).iter_rows(named=True):
            sector_by_sym[str(row["symbol"])] = str(row["industry_code"])

    seeds: list[StockSeed] = []
    for sym in [str(s) for s in day["symbol"].unique().to_list()]:
        r20 = _symbol_ret(prices, sym, 20)
        seeds.append(
            StockSeed(
                symbol=sym,
                name=names.get(sym, sym),
                sector_code=sector_by_sym.get(sym, "UNKNOWN"),
                ret_20d=r20,
                preliminary_score=max(0.0, min(1.0, 0.5 + r20)),
            )
        )
    seeds.sort(key=lambda s: s.preliminary_score, reverse=True)
    return seeds[: max(0, limit)]
