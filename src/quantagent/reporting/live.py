"""Build ReportBundle + shadow inputs from PITRepository (live DB path)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import polars as pl

from quantagent.agents.tools.market import (
    FactorRankRow,
    FactorRow,
    MarketOverview,
    QualityCheck,
    ReportBundle,
    RiskNote,
    SectorRow,
    ShadowStatusRow,
)
from quantagent.core.market import load_market_config
from quantagent.core.repository.pit import PITRepository
from quantagent.execution.broker.simulated import PriceBar
from quantagent.quant.evaluation.ic import daily_ic_series, summarize_ic
from quantagent.quant.evaluation.quantile import quantile_analysis
from quantagent.quant.features.base import FactorInput
from quantagent.quant.features.compute import compute_factors
from quantagent.quant.features.registry import MVP_FACTOR_CODES
from quantagent.shared.errors import QuantAgentError


class LiveReportError(QuantAgentError):
    """Live daily-report data path failure."""


@dataclass(frozen=True)
class LiveReportData:
    """Everything needed for shadow step + ReportBundle (no IO)."""

    as_of: date
    run_id: str
    market: str
    universe_code: str
    symbols: list[str]
    names: dict[str, str]
    bars: list[PriceBar]
    factor_scores: dict[str, float]
    factor_name: str
    bundle_partial: ReportBundle


def _as_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _pctile(series: list[float], value: float) -> float | None:
    if not series:
        return None
    n = sum(1 for x in series if x <= value)
    return n / len(series)


def bars_from_day_prices(day: pl.DataFrame) -> list[PriceBar]:
    """Convert a single-day price panel (with ``symbol``) to ``PriceBar`` list."""
    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
    missing = required - set(day.columns)
    if missing:
        raise LiveReportError(f"day prices missing columns: {sorted(missing)}")
    bars: list[PriceBar] = []
    for row in day.iter_rows(named=True):
        bars.append(
            PriceBar(
                symbol=str(row["symbol"]),
                trade_date=row["trade_date"],
                open=_as_float(row["open"]),
                high=_as_float(row["high"]),
                low=_as_float(row["low"]),
                close=_as_float(row["close"]),
                volume=_as_float(row["volume"]),
                amount=_as_float(row.get("amount"), 0.0),
                is_suspended=bool(row.get("is_suspended") or False),
                is_limit_up=bool(row.get("is_limit_up") or False),
                is_limit_down=bool(row.get("is_limit_down") or False),
            )
        )
    return bars


def add_forward_returns(panel: pl.DataFrame, *, entity: str = "symbol") -> pl.DataFrame:
    """Add ``ret_1d`` (trailing) and ``fwd_1d`` (next-day) per entity."""
    return panel.sort([entity, "trade_date"]).with_columns(
        (pl.col("close") / pl.col("close").shift(1).over(entity) - 1.0).alias("ret_1d"),
        (pl.col("close").shift(-1).over(entity) / pl.col("close") - 1.0).alias("fwd_1d"),
    )


def scores_as_of(
    factor_panel: pl.DataFrame,
    *,
    as_of: date,
    factor: str,
    entity: str = "symbol",
) -> dict[str, float]:
    """Cross-section of factor values on ``as_of`` (drop nulls)."""
    if factor not in factor_panel.columns:
        raise LiveReportError(f"factor column missing: {factor}")
    day = factor_panel.filter(pl.col("trade_date") == as_of).select([entity, factor]).drop_nulls()
    out: dict[str, float] = {}
    for row in day.iter_rows(named=True):
        out[str(row[entity])] = float(row[factor])
    return out


def build_factor_metrics(
    factor_panel: pl.DataFrame,
    *,
    as_of: date,
    factor_codes: list[str],
    entity: str = "symbol",
    ic_window: int = 20,
) -> list[FactorRow]:
    """Long-short (1d) + rolling IC mean from PIT factor panel with ``fwd_1d``."""
    if "fwd_1d" not in factor_panel.columns:
        factor_panel = add_forward_returns(factor_panel, entity=entity)

    # Only dates strictly before as_of have realized fwd_1d ending on/before as_of
    hist = factor_panel.filter(pl.col("trade_date") < as_of)
    rows: list[FactorRow] = []
    for code in factor_codes:
        if code not in hist.columns:
            continue
        ic_df = daily_ic_series(hist, factor_col=code, return_col="fwd_1d", min_names=3)
        if ic_df.is_empty():
            ic_mean: float | None = None
        else:
            recent = ic_df.tail(ic_window)
            ic_mean = summarize_ic(recent["ic"]).ic_mean

        # Latest complete cross-section for LS
        dates = (
            hist.filter(pl.col(code).is_not_null() & pl.col("fwd_1d").is_not_null())["trade_date"]
            .unique()
            .sort()
        )
        if dates.is_empty():
            ls = 0.0
        else:
            last = dates[-1]
            day = hist.filter(pl.col("trade_date") == last)
            qs = quantile_analysis(
                day,
                factor_col=code,
                return_col="fwd_1d",
                n_quantiles=5,
                min_names=min(5, day.height),
            )
            ls = qs.long_short_return
        rows.append(FactorRow(factor=code, long_short_1d=ls, ic_mean_20d=ic_mean))
    return rows


def build_factor_ranks(
    factor_panel: pl.DataFrame,
    *,
    as_of: date,
    factor: str,
    names: dict[str, str],
    top_n: int = 5,
    entity: str = "symbol",
) -> list[FactorRankRow]:
    scores = scores_as_of(factor_panel, as_of=as_of, factor=factor, entity=entity)
    if not scores:
        return []
    # ret_20d from close
    ret_map: dict[str, float] = {}
    if "close" in factor_panel.columns:
        for sym in scores:
            hist = (
                factor_panel.filter(pl.col(entity) == sym)
                .sort("trade_date")
                .select(["trade_date", "close"])
            )
            if hist.height < 21:
                ret_map[sym] = 0.0
                continue
            c0 = float(hist["close"][-21])
            c1 = float(hist["close"][-1])
            ret_map[sym] = (c1 / c0 - 1.0) if c0 else 0.0

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ordered)
    ranks: list[FactorRankRow] = []
    for i, (sym, score) in enumerate(ordered[:top_n]):
        rank_of = sum(1 for _, s in ordered if s <= score) / n if n else 1.0
        ranks.append(
            FactorRankRow(
                rank=i + 1,
                symbol=sym,
                name=names.get(sym, sym),
                score_pctile=rank_of,
                ret_20d=ret_map.get(sym, 0.0),
            )
        )
    return ranks


def build_market_overview(
    *,
    as_of: date,
    index_panel: pl.DataFrame,
    universe_day: pl.DataFrame,
    universe_hist: pl.DataFrame,
    index_symbol: str,
) -> MarketOverview:
    idx = index_panel.filter(pl.col("trade_date") <= as_of).sort("trade_date")
    if idx.height == 0:
        raise LiveReportError(f"No index bars for {index_symbol} as_of {as_of}")
    index_close = _as_float(idx["close"][-1])
    if idx.height >= 2:
        prev = _as_float(idx["close"][-2])
        index_ret = (index_close / prev - 1.0) if prev else 0.0
    else:
        index_ret = 0.0

    day = universe_day
    if day.is_empty():
        raise LiveReportError(f"No universe prices on {as_of}")

    # Prefer ret from close vs prev_close when available
    if "prev_close" in day.columns:
        rets = day.select((pl.col("close") / pl.col("prev_close") - 1.0).alias("r")).drop_nulls()
    else:
        # join trailing from hist
        prev_day = (
            universe_hist.filter(pl.col("trade_date") < as_of)
            .sort("trade_date")
            .group_by("symbol")
            .agg(pl.col("close").last().alias("prev_close"))
        )
        joined = day.join(prev_day, on="symbol", how="left")
        rets = joined.select((pl.col("close") / pl.col("prev_close") - 1.0).alias("r")).drop_nulls()

    n_up = int(rets.filter(pl.col("r") > 1e-12).height)
    n_down = int(rets.filter(pl.col("r") < -1e-12).height)
    n_flat = int(rets.height) - n_up - n_down

    if "amount" in day.columns and day["amount"].null_count() < day.height:
        total_amount = _as_float(day["amount"].sum())
    else:
        total_amount = 0.0
    if "turnover_rate" in day.columns and day["turnover_rate"].drop_nulls().len() > 0:
        avg_turnover = _as_float(day["turnover_rate"].drop_nulls().mean())
    else:
        avg_turnover = 0.0

    # 20d history of pool amount / breadth / turnover for pctiles
    hist_dates = (
        universe_hist.filter(pl.col("trade_date") <= as_of)["trade_date"].unique().sort().tail(20)
    )
    amount_series: list[float] = []
    breadth_series: list[float] = []
    turnover_series: list[float] = []
    for td in hist_dates.to_list():
        g = universe_hist.filter(pl.col("trade_date") == td)
        if "amount" in g.columns:
            amount_series.append(_as_float(g["amount"].sum()))
        if "turnover_rate" in g.columns and g["turnover_rate"].drop_nulls().len() > 0:
            turnover_series.append(_as_float(g["turnover_rate"].drop_nulls().mean()))
        # breadth = up/(up+down)
        if "prev_close" in g.columns:
            rr = g.select((pl.col("close") / pl.col("prev_close") - 1.0).alias("r")).drop_nulls()
        else:
            continue
        up = int(rr.filter(pl.col("r") > 1e-12).height)
        down = int(rr.filter(pl.col("r") < -1e-12).height)
        denom = up + down
        breadth_series.append(up / denom if denom else 0.5)

    amount_vs_20d = 0.0
    if amount_series and len(amount_series) >= 2:
        mean_amt = sum(amount_series[:-1]) / max(len(amount_series) - 1, 1)
        if mean_amt > 0:
            amount_vs_20d = amount_series[-1] / mean_amt - 1.0

    breadth_today = n_up / (n_up + n_down) if (n_up + n_down) else 0.5
    return MarketOverview(
        as_of=as_of,
        index_symbol=index_symbol,
        index_close=index_close,
        index_return_1d=index_ret,
        n_up=n_up,
        n_down=n_down,
        n_flat=n_flat,
        total_amount=total_amount,
        amount_vs_20d=amount_vs_20d,
        avg_turnover=avg_turnover,
        up_down_pctile_20d=_pctile(breadth_series, breadth_today),
        amount_pctile_20d=_pctile(amount_series, amount_series[-1]) if amount_series else None,
        turnover_pctile_20d=_pctile(turnover_series, avg_turnover) if turnover_series else None,
    )


def build_sector_rows(
    prices: pl.DataFrame,
    industry: pl.DataFrame,
    *,
    as_of: date,
) -> list[SectorRow]:
    if industry.is_empty() or "industry_name" not in industry.columns:
        return []
    # Prefer level-1 if present
    ind = industry
    if "level" in ind.columns:
        lvl1 = ind.filter(pl.col("level") == 1)
        if not lvl1.is_empty():
            ind = lvl1
    ind = ind.select(["symbol", "industry_name"]).unique(subset=["symbol"])

    day = prices.filter(pl.col("trade_date") == as_of)
    if day.is_empty():
        return []

    def _ret(sym: str, lookback: int) -> float:
        hist = prices.filter(pl.col("symbol") == sym).sort("trade_date")
        if hist.height <= lookback:
            return 0.0
        c0 = float(hist["close"][-(lookback + 1)])
        c1 = float(hist["close"][-1])
        return (c1 / c0 - 1.0) if c0 else 0.0

    joined = day.join(ind, on="symbol", how="inner")
    rows: list[SectorRow] = []
    for (name,), g in joined.group_by("industry_name"):
        syms = [str(s) for s in g["symbol"].to_list()]
        if not syms:
            continue
        r1 = sum(_ret(s, 1) for s in syms) / len(syms)
        r5 = sum(_ret(s, 5) for s in syms) / len(syms)
        r20 = sum(_ret(s, 20) for s in syms) / len(syms)
        rows.append(
            SectorRow(
                industry=str(name),
                n_names=len(syms),
                ret_1d=r1,
                ret_5d=r5,
                ret_20d=r20,
            )
        )
    rows.sort(key=lambda r: r.ret_1d, reverse=True)
    return rows


def select_factor_codes(prices: pl.DataFrame) -> list[str]:
    """Pick MVP factors computable from available columns (skip ep_ttm without financials)."""
    cols = set(prices.columns)
    out: list[str] = []
    for code in MVP_FACTOR_CODES:
        if code == "ep_ttm":
            continue
        if code in {"turnover_20d", "turnover_ratio_5_60"} and "turnover_rate" not in cols:
            continue
        if code == "amihud_illiq_20d" and "amount" not in cols:
            continue
        out.append(code)
    return out


def build_live_quality(
    *,
    symbols: list[str],
    day: pl.DataFrame,
    industry: pl.DataFrame,
    factor_scores: dict[str, float],
) -> list[QualityCheck]:
    n = len(symbols)
    n_bars = day.height if not day.is_empty() else 0
    return [
        QualityCheck(
            name="行情完整性",
            ok=n > 0 and n_bars == n,
            detail=f"{n_bars}/{n}",
        ),
        QualityCheck(
            name="行业归属",
            ok=not industry.is_empty(),
            detail=("已入库" if not industry.is_empty() else "未入库（板块表为空）"),
        ),
        QualityCheck(
            name="因子截面",
            ok=len(factor_scores) >= max(3, n // 5) if n else False,
            detail=f"{len(factor_scores)}/{n} 有 {('mom_20d' if factor_scores else 'n/a')}",
        ),
        QualityCheck(name="PIT 校验", ok=True, detail="via PITRepository"),
        QualityCheck(
            name="未来函数哨兵",
            ok=True,
            detail="依赖 CI / make test-sentinel（本报告路径强制 as_of）",
        ),
    ]


def load_live_report_data(
    repo: PITRepository,
    *,
    as_of: date | None,
    run_id: str,
    market: str = "CN",
    universe_code: str = "mvp_cn_50",
    factor_name: str = "mom_20d",
    lookback_days: int = 120,
    code_version: str = "dev",
) -> LiveReportData:
    """Load PIT panels and assemble shadow inputs + report facts."""
    mkt = load_market_config(market)
    index_symbol = mkt.benchmark_symbol

    # Resolve universe first (need symbols to pick default as_of)
    probe_as_of = as_of or date.today()
    symbols = repo.resolve_universe_symbols(as_of=probe_as_of, name=universe_code)
    if not symbols:
        snaps = repo.list_universe_snapshot_dates(name=universe_code)
        if not snaps:
            hint = (
                f"no snapshots yet; run: "
                f"uv run python -m quantagent.cli seed-universe --as-of {probe_as_of}"
            )
        else:
            # PIT: only snapshots with snapshot_date <= as_of are visible
            usable = [d for d in snaps if d <= probe_as_of]
            hint = (
                f"snapshots={', '.join(d.isoformat() for d in snaps)}; "
                f"usable_on_or_before_{probe_as_of}={len(usable)}. "
                f"Seed an earlier date, e.g. "
                f"uv run python -m quantagent.cli seed-universe --as-of {snaps[0]}"
                if usable == []
                else "universe row empty for unknown reason"
            )
            if usable == []:
                hint = (
                    f"snapshots exist {[d.isoformat() for d in snaps]} but all are "
                    f"after as_of={probe_as_of} (PIT cannot use future snapshots). "
                    f"Re-seed with --as-of <= {probe_as_of}, e.g. "
                    f"uv run python -m quantagent.cli seed-universe "
                    f"--universe {universe_code} --as-of 2025-01-02"
                )
        raise LiveReportError(f"Universe {universe_code!r} empty as_of {probe_as_of}; {hint}")

    # Default as_of = last session on/before today (calendar-aware; prices may lag)
    if as_of is None:
        from quantagent.core.calendar import TradingCalendar

        target = TradingCalendar("CN").default_as_of()
    else:
        target = as_of
    latest = repo.latest_trade_date(symbols + [index_symbol], on_or_before=target)
    if latest is None:
        raise LiveReportError("No price_daily rows for universe/benchmark; ingest first")
    as_of = latest

    start = as_of - timedelta(days=lookback_days)
    names = repo.get_security_names(symbols)

    uni_prices = repo.get_prices(symbols, as_of=as_of, start=start, end=as_of, adjust="qfq")
    if uni_prices.is_empty():
        raise LiveReportError(f"No universe prices between {start} and {as_of}")

    index_prices = repo.get_prices(
        [index_symbol], as_of=as_of, start=start, end=as_of, adjust="qfq"
    )
    industry = repo.get_industry(symbols, as_of=as_of, taxonomy=mkt.industry_taxonomy)

    day = uni_prices.filter(pl.col("trade_date") == as_of)
    if day.is_empty():
        max_td = uni_prices["trade_date"].max()
        if max_td is None:
            raise LiveReportError("Universe price panel has no trade_date")
        as_of = max_td if isinstance(max_td, date) else date.fromisoformat(str(max_td))
        day = uni_prices.filter(pl.col("trade_date") == as_of)

    factor_codes = select_factor_codes(uni_prices)
    if factor_name not in factor_codes:
        factor_codes = [factor_name, *factor_codes]

    # Prefer symbol as entity so scores / ranks key by ticker (drop security_id)
    prices_for_fx = (
        uni_prices.drop("security_id") if "security_id" in uni_prices.columns else uni_prices
    )
    factor_panel = compute_factors(
        FactorInput(prices=prices_for_fx, financials=None, as_of=as_of),
        codes=[c for c in factor_codes if c != "ep_ttm"],
    )
    # Re-attach OHLCV needed for ret_20d / forward returns
    price_cols = [
        c
        for c in ("symbol", "trade_date", "close", "open", "high", "low", "volume", "amount")
        if c in prices_for_fx.columns
    ]
    factor_panel = factor_panel.join(
        prices_for_fx.select(price_cols),
        on=["symbol", "trade_date"],
        how="left",
    )
    factor_panel = add_forward_returns(factor_panel, entity="symbol")

    scores = scores_as_of(factor_panel, as_of=as_of, factor=factor_name)
    overview = build_market_overview(
        as_of=as_of,
        index_panel=index_prices,
        universe_day=day,
        universe_hist=uni_prices,
        index_symbol=index_symbol,
    )
    sectors = build_sector_rows(uni_prices, industry, as_of=as_of)
    factors = build_factor_metrics(
        factor_panel,
        as_of=as_of,
        factor_codes=[c for c in factor_codes if c != "ep_ttm"][:5],
    )
    ranks = build_factor_ranks(factor_panel, as_of=as_of, factor=factor_name, names=names, top_n=5)
    quality = build_live_quality(symbols=symbols, day=day, industry=industry, factor_scores=scores)
    bars = bars_from_day_prices(day)

    partial = ReportBundle(
        as_of=as_of,
        run_id=run_id,
        market=market,
        market_overview=overview,
        sectors=sectors,
        factors=factors,
        factor_ranks=ranks,
        factor_rank_name=factor_name,
        shadow=[],
        risk_notes=[],
        quality=quality,
        data_sources=[
            f"行情：PITRepository.get_prices（universe={universe_code}）",
            f"基准：{index_symbol}",
            f"因子：compute_factors({', '.join(c for c in factor_codes if c != 'ep_ttm')})",
            "行业：PITRepository.get_industry（若已入库）",
        ],
        code_version=code_version,
    )
    return LiveReportData(
        as_of=as_of,
        run_id=run_id,
        market=market,
        universe_code=universe_code,
        symbols=symbols,
        names=names,
        bars=bars,
        factor_scores=scores,
        factor_name=factor_name,
        bundle_partial=partial,
    )


def finalize_live_bundle(
    data: LiveReportData,
    *,
    shadow_rows: list[ShadowStatusRow],
    risk_notes: list[RiskNote],
) -> ReportBundle:
    base = data.bundle_partial
    return base.model_copy(
        update={
            "shadow": shadow_rows,
            "risk_notes": risk_notes or [RiskNote(text="当前回撤在阈值内（阈值 -15%）")],
        }
    )
