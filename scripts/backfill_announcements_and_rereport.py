#!/usr/bin/env python3
"""Backfill EM announcements for a date range, extract events, optionally re-report."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from quantagent.agents.news_extractor import (
    EXTRACTOR_MODEL,
    EXTRACTOR_VERSION,
    RuleNewsExtractor,
)
from quantagent.core.calendar import TradingCalendar
from quantagent.data.collectors.news import EmAnnouncementCollector
from quantagent.data.loaders import EventLoader, NewsLoader
from quantagent.data.normalizers.news import NewsNormalizer
from quantagent.shared.errors import SourceUnavailableError


async def _backfill_announcements(start: date, end: date) -> dict[str, int]:
    cal = TradingCalendar("CN")
    if cal.is_empty():
        days = []
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                days.append(cur)
            cur += timedelta(days=1)
    else:
        days = cal.trading_days(start, end)

    norm = NewsNormalizer()
    loader = NewsLoader()
    collector = EmAnnouncementCollector(fallback_days=0, rate_limit=0.25)
    loaded = 0
    empty = 0
    failed = 0
    for i, day in enumerate(days, start=1):
        try:
            batch = await collector.collect(day)
            df = norm.normalize(batch)
            if df.is_empty():
                empty += 1
                print(f"[{i}/{len(days)}] {day} empty")
                continue
            result = loader.load(
                df,
                source=batch.source,
                raw_path=batch.raw_path,
                target_date=day,
            )
            n = int(result["rows_loaded"])  # type: ignore[arg-type]
            loaded += n
            print(f"[{i}/{len(days)}] {day} loaded={n}")
        except SourceUnavailableError as exc:
            empty += 1
            print(f"[{i}/{len(days)}] {day} unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[{i}/{len(days)}] {day} FAIL {type(exc).__name__}: {exc}")
    return {"days": len(days), "rows_loaded": loaded, "empty": empty, "failed": failed}


def _extract(*, limit: int) -> dict[str, int]:
    event_loader = EventLoader()
    rows = event_loader.fetch_unextracted_news(limit=limit)
    if not rows:
        print("extract: no unextracted rows")
        return {"scanned": 0, "events": 0, "links": 0}
    extractor = RuleNewsExtractor()
    items = [
        (
            int(row["news_id"]),
            row["published_at"],
            extractor.extract(
                title=str(row["title"]),
                body=row.get("body"),
                announce_type=row.get("announce_type"),
                hint_symbol=row.get("related_symbol"),
            ),
        )
        for row in rows
    ]
    stats = event_loader.load_extractions(
        items,
        extractor_model=EXTRACTOR_MODEL,
        extractor_version=EXTRACTOR_VERSION,
    )
    print(
        f"extract scanned={len(items)} events={stats['events']} links={stats['links']}"
    )
    return {
        "scanned": len(items),
        "events": int(stats["events"]),
        "links": int(stats["links"]),
    }


def _relink_symbols() -> dict[str, int]:
    loader = EventLoader()
    filled = loader.backfill_related_symbols_from_urls()
    stats = loader.backfill_subject_links_from_news()
    print(f"relink related_symbol_filled={filled} {stats}")
    return {"related_symbol_filled": filled, **stats}


async def _rereport(days: list[date], *, out_dir: Path, shadow_dir: Path) -> int:
    from quantagent.reporting.pipeline import run_daily_pipeline

    ok = 0
    for day in days:
        path = await run_daily_pipeline(
            as_of=day,
            out_dir=out_dir,
            shadow_dir=shadow_dir,
            synthetic=False,
            write_cost_log=False,
        )
        text = path.read_text(encoding="utf-8")
        has_events = "## 二、重要事件" in text
        print(f"report {day} -> {path} events_section={has_events}")
        ok += 1
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 2))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 12))
    parser.add_argument("--extract-limit", type=int, default=5000)
    parser.add_argument("--skip-announce", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument(
        "--relink",
        action="store_true",
        help="Fill news.related_symbol from EM URLs and attach missing event_security",
    )
    parser.add_argument("--rereport", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("docs/daily-reports"))
    parser.add_argument("--shadow-dir", type=Path, default=Path("data/shadow"))
    args = parser.parse_args()

    if not args.skip_announce:
        stats = asyncio.run(_backfill_announcements(args.start, args.end))
        print(f"announce done {stats}")
        if stats["failed"]:
            return 1

    if not args.skip_extract:
        _extract(limit=args.extract_limit)

    if args.relink:
        _relink_symbols()

    if args.rereport:
        cal = TradingCalendar("CN")
        if cal.is_empty():
            days = [
                args.start + timedelta(days=i)
                for i in range((args.end - args.start).days + 1)
                if (args.start + timedelta(days=i)).weekday() < 5
            ]
        else:
            days = cal.trading_days(args.start, args.end)
        # Only re-report days that already had a report file (Gate1 streak).
        existing = [
            d for d in days if (args.out / f"{d.isoformat()}.md").exists()
        ]
        if not existing:
            print("rereport: no existing daily-report files in range", file=sys.stderr)
            return 1
        n = asyncio.run(
            _rereport(existing, out_dir=args.out, shadow_dir=args.shadow_dir)
        )
        print(f"rereport done n={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
