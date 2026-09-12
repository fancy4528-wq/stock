"""Incremental price/index ingest + universe seed for live daily jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from quantagent.core.calendar import TradingCalendar
from quantagent.core.market import load_market_config
from quantagent.core.universe import load_universe_config, seed_universe_snapshot
from quantagent.data.collectors.akshare import AkshareIndexCollector, AksharePriceCollector
from quantagent.data.collectors.baostock import BaostockPriceCollector
from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.loaders import PriceLoader
from quantagent.data.normalizers.price import PriceNormalizer
from quantagent.data.ops.degrade import try_collect_with_fallback
from quantagent.data.ops.price_dual_check import validate_prices_dual
from quantagent.reporting.pipeline import make_run_id
from quantagent.shared.errors import DataError


@dataclass
class DailyRefreshResult:
    as_of: date
    start: date
    end: date
    universe_code: str
    n_symbols: int
    price_rows: int = 0
    index_rows: int = 0
    n_seeded: int = 0
    missing: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    run_id: str | None = None


def _ingest_window_start(
    as_of: date,
    *,
    lookback_sessions: int,
    market: str,
) -> date:
    """Start date for incremental pull (includes a few prior sessions)."""
    if lookback_sessions <= 1:
        return as_of
    cal = TradingCalendar(market)
    if cal.is_empty():
        # Calendar not loaded yet — calendar-day fallback.
        from datetime import timedelta

        return as_of - timedelta(days=max(lookback_sessions * 2, 7))
    try:
        return cal.prev_trading_day(as_of, n=lookback_sessions - 1)
    except DataError:
        return as_of


def _peer_source(source: str) -> str:
    return "baostock" if source == "akshare" else "akshare"


def _price_collector(source: str, archive_root: Path | None) -> Collector:
    if source == "akshare":
        return AksharePriceCollector(archive_root=archive_root)
    if source == "baostock":
        return BaostockPriceCollector(archive_root=archive_root)
    raise ValueError(f"unsupported price source: {source}")


async def _collect_price_batch(
    *,
    symbols: list[str],
    start: date,
    end: date,
    source: str,
    archive_root: Path | None,
) -> tuple[RawBatch, str | None]:
    """Collect price batch; fallback to peer source on ``SourceUnavailableError``."""
    primary = _price_collector(source, archive_root)
    fallback_src = _peer_source(source)
    fallback = _price_collector(fallback_src, archive_root)

    async def _primary() -> RawBatch:
        return await primary.collect(end, symbols=symbols, start=start, end=end)

    async def _fallback() -> RawBatch:
        return await fallback.collect(end, symbols=symbols, start=start, end=end)

    batch, degraded = await try_collect_with_fallback(
        _primary,
        _fallback,
        primary_source=source,
        fallback_source=fallback_src,
        dataset="price_daily",
    )
    annotation = degraded.annotation() if degraded else None
    return batch, annotation


async def _collect_and_load_prices(
    *,
    symbols: list[str],
    start: date,
    end: date,
    source: str,
    kind: str,
    archive_root: Path | None,
    dual_check: bool = False,
    run_id: str | None = None,
    degraded_notes: list[str] | None = None,
) -> int:
    collector: Collector
    if kind == "index":
        if source != "akshare":
            raise ValueError("index ingest currently supports source=akshare only")
        collector = AkshareIndexCollector(archive_root=archive_root)
        batch = await collector.collect(end, symbols=symbols, start=start, end=end)
    else:
        batch, note = await _collect_price_batch(
            symbols=symbols,
            start=start,
            end=end,
            source=source,
            archive_root=archive_root,
        )
        if note and degraded_notes is not None:
            degraded_notes.append(note)
            print(f"daily_refresh DEGRADED: {note}")

    df = PriceNormalizer().normalize(batch)
    print(
        f"daily_refresh {kind} source={batch.source} batch_id={batch.batch_id} "
        f"rows_raw={batch.row_count} rows_norm={df.height} path={batch.raw_path}"
    )
    if not df.height:
        return 0

    if dual_check and kind == "price":
        peer_src = _peer_source(batch.source)
        peer_collector = _price_collector(peer_src, archive_root)
        peer_batch = await peer_collector.collect(end, symbols=symbols, start=start, end=end)
        peer_df = PriceNormalizer().normalize(peer_batch)
        validate_prices_dual(
            df,
            peer_df,
            check_date=end,
            persist=False,
            run_id=run_id,
        )

    result = PriceLoader().load(
        df,
        source=batch.source,
        raw_path=batch.raw_path,
        target_date=end,
    )
    print(
        f"daily_refresh loaded {kind} batch_id={result['batch_id']} "
        f"rows={result['rows_loaded']} status={result['status']}"
    )
    return int(result["rows_loaded"])


async def refresh_daily_market_data(
    *,
    as_of: date | None = None,
    universe_code: str = "mvp_cn_50",
    market: str = "CN",
    price_source: str = "baostock",
    lookback_sessions: int = 3,
    archive_root: Path | None = None,
    skip_ingest: bool = False,
    skip_seed: bool = False,
    dual_check: bool = False,
    run_id: str | None = None,
) -> DailyRefreshResult:
    """Ingest recent universe + benchmark bars, then seed ``universe_snapshot``.

    Designed for after-close live scheduling. Soft-missing symbols are OK
    (A5 may still be filling the 50-name pool); seeding uses whatever is in
    ``security`` already.
    """
    cal = TradingCalendar(market)
    session = as_of or cal.default_as_of()
    start = _ingest_window_start(session, lookback_sessions=lookback_sessions, market=market)
    end = session
    resolved_run_id = run_id or make_run_id(session, market)

    cfg = load_universe_config(universe_code)
    symbols = list(cfg.bootstrap_symbols)
    mkt = load_market_config(market)
    benchmark = mkt.benchmark_symbol

    price_rows = 0
    index_rows = 0
    degraded: list[str] = []
    if not skip_ingest:
        if symbols:
            price_rows = await _collect_and_load_prices(
                symbols=symbols,
                start=start,
                end=end,
                source=price_source,
                kind="price",
                archive_root=archive_root,
                dual_check=dual_check,
                run_id=resolved_run_id,
                degraded_notes=degraded,
            )
        # Index bars: akshare only today.
        index_rows = await _collect_and_load_prices(
            symbols=[benchmark],
            start=start,
            end=end,
            source="akshare",
            kind="index",
            archive_root=archive_root,
        )

    n_seeded = 0
    missing: list[str] = []
    if not skip_seed:
        seeded = seed_universe_snapshot(
            code=universe_code,
            as_of=session,
            require_all=False,
        )
        n_seeded_raw = seeded.get("n_seeded", 0)
        n_seeded = int(n_seeded_raw) if isinstance(n_seeded_raw, int) else int(str(n_seeded_raw))
        raw_missing = seeded.get("missing", [])
        if isinstance(raw_missing, list):
            missing = [str(s) for s in raw_missing]
        print(
            f"daily_refresh seeded universe={seeded['code']} as_of={seeded['as_of']} "
            f"n={n_seeded} missing={len(missing)}"
        )

    return DailyRefreshResult(
        as_of=session,
        start=start,
        end=end,
        universe_code=universe_code,
        n_symbols=len(symbols),
        price_rows=price_rows,
        index_rows=index_rows,
        n_seeded=n_seeded,
        missing=missing,
        degraded=degraded,
        run_id=resolved_run_id,
    )
