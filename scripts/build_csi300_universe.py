"""Fetch HS300 membership → write ``config/universe/csi300.yaml`` + hist union list.

Order of operations for Gate 3 CSI300 L1:
  1. This script (current members + month-end historical union)
  2. ``make backfill-10y UNIVERSE=csi300 SYMBOLS_FILE=data/universes/csi300_hist_union.txt``
  3. ``make backfill-adjust-10y`` / valuation / industry (same UNIVERSE + SYMBOLS_FILE)
  4. ``make backfill-universe-monthly UNIVERSE=csi300 FROM_INDEX=hs300``
  5. ``make evaluate-real UNIVERSE=csi300 OUT_DIR=docs/factor-reports-csi300``
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from quantagent.core.calendar import TradingCalendar
from quantagent.data.collectors.baostock import BaostockIndexConstituentCollector


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("repo root not found")


def _write_yaml(path: Path, *, code: str, name: str, symbols: list[str]) -> None:
    doc = {
        "code": code,
        "name": name,
        "market": "CN",
        "rule": {
            "base": "csi300",
            "note": (
                "bootstrap_symbols = current HS300 via baostock query_hs300_stocks; "
                "monthly snapshots use dated constituents when "
                "backfill_universe_snapshots --from-index hs300"
            ),
            "snapshot_frequency": "monthly",
        },
        "bootstrap_symbols": symbols,
        "survivorship_probes": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_symbols_file(path: Path, symbols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(symbols) + "\n", encoding="utf-8")


def _chunked(items: list[date], size: int) -> list[list[date]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--market", default="CN")
    p.add_argument(
        "--skip-hist",
        action="store_true",
        help="Only fetch latest HS300 (skip month-end historical union)",
    )
    p.add_argument(
        "--chunk-months",
        type=int,
        default=12,
        help="Month-ends per baostock login (default 12)",
    )
    p.add_argument(
        "--yaml-out",
        type=Path,
        default=None,
        help="Default: config/universe/csi300.yaml",
    )
    p.add_argument(
        "--union-out",
        type=Path,
        default=None,
        help="Default: data/universes/csi300_hist_union.txt",
    )
    args = p.parse_args()

    root = _repo_root()
    yaml_out = args.yaml_out or (root / "config" / "universe" / "csi300.yaml")
    union_out = args.union_out or (root / "data" / "universes" / "csi300_hist_union.txt")

    coll = BaostockIndexConstituentCollector()

    print("fetch latest HS300...", flush=True)
    current = await coll.fetch_symbols(index="hs300", as_of=None)
    print(f"current HS300 n={len(current)}", flush=True)
    if len(current) < 200:
        print(f"FAIL: expected ~300 HS300 names, got {len(current)}", flush=True)
        return 2

    _write_yaml(yaml_out, code="csi300", name="沪深300", symbols=current)
    print(f"wrote {yaml_out}", flush=True)

    union: set[str] = set(current)
    _write_symbols_file(union_out, sorted(union))

    if not args.skip_hist:
        cal = TradingCalendar(args.market)
        if cal.is_empty():
            print(
                "WARN: trading_calendar empty; hist union = current only. "
                "Run make ingest-calendar then re-run without --skip-hist.",
                flush=True,
            )
        else:
            sessions = cal.month_end_sessions(args.start, args.end)
            chunks = _chunked(sessions, max(1, args.chunk_months))
            print(
                f"hist union month-ends={len(sessions)} chunks={len(chunks)} "
                f"window=[{args.start}, {args.end}]",
                flush=True,
            )
            done = 0
            for ci, chunk in enumerate(chunks, 1):
                print(f"chunk [{ci}/{len(chunks)}] n={len(chunk)} ...", flush=True)
                try:
                    batch = await coll.fetch_symbols_many(list(chunk), index="hs300")
                except Exception as exc:  # noqa: BLE001
                    print(f"FAIL chunk {ci}: {exc}", flush=True)
                    continue
                for sess in chunk:
                    syms = batch.get(sess.isoformat(), [])
                    before = len(union)
                    union.update(syms)
                    done += 1
                    print(
                        f"[{done}/{len(sessions)}] {sess.isoformat()} "
                        f"n={len(syms)} union={len(union)} (+{len(union) - before})",
                        flush=True,
                    )
                _write_symbols_file(union_out, sorted(union))

    ordered = sorted(union)
    _write_symbols_file(union_out, ordered)
    print(f"wrote hist union n={len(ordered)} → {union_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
