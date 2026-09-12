"""Chunked adjust_factor backfill for mvp_cn_50."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from quantagent.core.universe import load_universe_config
from quantagent.data.collectors.baostock import BaostockAdjustCollector
from quantagent.data.loaders.adjust import AdjustLoader
from quantagent.data.normalizers.adjust import AdjustNormalizer


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="mvp_cn_50")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = p.parse_args()

    symbols = list(load_universe_config(args.universe).bootstrap_symbols)
    print(
        f"adjust backfill n={len(symbols)} window=[{args.start}, {args.end}]",
        flush=True,
    )
    failures: list[str] = []
    total = 0
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ...", flush=True)
        try:
            collector = BaostockAdjustCollector()
            batch = await collector.collect(
                args.end, symbols=[sym], start=args.start, end=args.end
            )
            df = AdjustNormalizer().normalize(batch)
            if df.height == 0:
                print(f"SKIP empty {sym}", flush=True)
                continue
            result = AdjustLoader().load(
                df,
                source=batch.source,
                raw_path=batch.raw_path,
                target_date=args.end,
            )
            total += int(result["rows_loaded"])
            print(f"OK {sym} rows={result['rows_loaded']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {sym}: {exc}", flush=True)
            failures.append(sym)
    print(f"DONE adjust rows={total} failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
