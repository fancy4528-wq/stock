"""Chunked 10y price backfill for mvp_cn_50 (progress + resume-friendly)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from quantagent.core.universe import load_universe_config
from quantagent.data.collectors.baostock import BaostockPriceCollector
from quantagent.data.loaders import PriceLoader
from quantagent.data.normalizers.price import PriceNormalizer
from quantagent.shared.config import get_settings


def _already_covered(symbol: str, start: date, end: date, min_bars: int) -> bool:
    eng = create_engine(get_settings().database_url, pool_pre_ping=True)
    with eng.connect() as conn:
        n = conn.execute(
            text(
                """
                SELECT count(*) FROM price_daily p
                JOIN security s ON s.security_id = p.security_id
                WHERE s.symbol = :sym
                  AND p.trade_date >= :start
                  AND p.trade_date <= :end
                """
            ),
            {"sym": symbol, "start": start, "end": end},
        ).scalar_one()
    return int(n) >= min_bars


async def _ingest_one(
    symbol: str,
    *,
    start: date,
    end: date,
    archive_root: Path | None,
) -> int:
    collector = BaostockPriceCollector(archive_root=archive_root)
    batch = await collector.collect(end, symbols=[symbol], start=start, end=end)
    df = PriceNormalizer().normalize(batch)
    if df.height == 0:
        print(f"SKIP empty {symbol}", flush=True)
        return 0
    result = PriceLoader().load(
        df,
        source=batch.source,
        raw_path=batch.raw_path,
        target_date=end,
    )
    rows = int(result["rows_loaded"])
    print(
        f"OK {symbol} rows={rows} batch_id={result['batch_id']} path={batch.raw_path}",
        flush=True,
    )
    return rows


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="mvp_cn_50")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--min-bars", type=int, default=2000, help="Skip if already >= this many bars")
    p.add_argument("--archive-root", type=Path, default=None)
    p.add_argument("--only", default=None, help="Comma-separated symbols to restrict")
    args = p.parse_args()

    cfg = load_universe_config(args.universe)
    symbols = list(cfg.bootstrap_symbols)
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        symbols = [s for s in symbols if s in want]

    print(
        f"backfill universe={args.universe} n={len(symbols)} "
        f"window=[{args.start}, {args.end}]",
        flush=True,
    )
    total = 0
    failures: list[str] = []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ...", flush=True)
        if _already_covered(sym, args.start, args.end, args.min_bars):
            print(f"SKIP covered {sym}", flush=True)
            continue
        try:
            total += await _ingest_one(
                sym, start=args.start, end=args.end, archive_root=args.archive_root
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {sym}: {exc}", flush=True)
            failures.append(sym)

    print(f"DONE rows_loaded={total} failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
