"""Chunked valuation_daily backfill for mvp_cn_50 (baostock pe/pb/ps)."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import create_engine, text

from quantagent.core.universe import load_universe_config
from quantagent.data.collectors.baostock import BaostockValuationCollector
from quantagent.data.loaders.valuation import ValuationLoader
from quantagent.data.normalizers.valuation import ValuationNormalizer
from quantagent.shared.config import get_settings


def _already_covered(symbol: str, start: date, end: date, min_bars: int) -> bool:
    eng = create_engine(get_settings().database_url, pool_pre_ping=True)
    with eng.connect() as conn:
        n = conn.execute(
            text(
                """
                SELECT count(*) FROM valuation_daily v
                JOIN security s ON s.security_id = v.security_id
                WHERE s.symbol = :sym
                  AND v.trade_date >= :start
                  AND v.trade_date <= :end
                """
            ),
            {"sym": symbol, "start": start, "end": end},
        ).scalar_one()
    return int(n) >= min_bars


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="mvp_cn_50")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument(
        "--min-bars",
        type=int,
        default=2000,
        help="Skip symbol if already >= this many valuation rows",
    )
    p.add_argument("--only", default=None, help="Comma-separated symbols to restrict")
    args = p.parse_args()

    symbols = list(load_universe_config(args.universe).bootstrap_symbols)
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        symbols = [s for s in symbols if s in want]

    print(
        f"valuation backfill n={len(symbols)} window=[{args.start}, {args.end}]",
        flush=True,
    )
    failures: list[str] = []
    total = 0
    for i, sym in enumerate(symbols, 1):
        if _already_covered(sym, args.start, args.end, args.min_bars):
            print(f"[{i}/{len(symbols)}] {sym} SKIP covered", flush=True)
            continue
        print(f"[{i}/{len(symbols)}] {sym} ...", flush=True)
        try:
            collector = BaostockValuationCollector()
            batch = await asyncio.wait_for(
                collector.collect(
                    args.end, symbols=[sym], start=args.start, end=args.end
                ),
                timeout=180.0,
            )
            df = ValuationNormalizer().normalize(batch)
            if df.height == 0:
                print(f"SKIP empty {sym}", flush=True)
                continue
            result = ValuationLoader().load(
                df,
                source=batch.source,
                raw_path=batch.raw_path,
                target_date=args.end,
            )
            total += int(result["rows_loaded"])
            print(f"OK {sym} rows={result['rows_loaded']}", flush=True)
        except TimeoutError:
            print(f"FAIL {sym}: collect timeout 180s", flush=True)
            failures.append(sym)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {sym}: {exc}", flush=True)
            failures.append(sym)
    print(f"DONE valuation rows={total} failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
