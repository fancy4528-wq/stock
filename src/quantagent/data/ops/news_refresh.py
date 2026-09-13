"""Daily news / announcement ingest + rule_v1 event extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from quantagent.agents.news_extractor import (
    EXTRACTOR_MODEL,
    EXTRACTOR_VERSION,
    RuleNewsExtractor,
)
from quantagent.data.collectors.news import (
    ClsNewsCollector,
    EmAnnouncementCollector,
    EmNewsCollector,
)
from quantagent.data.loaders import EventLoader, NewsLoader
from quantagent.data.normalizers.news import NewsNormalizer
from quantagent.shared.errors import SourceUnavailableError


@dataclass
class DailyNewsRefreshResult:
    as_of: date
    news_rows: int = 0
    announcement_rows: int = 0
    events: int = 0
    event_links: int = 0
    degraded: list[str] = field(default_factory=list)


async def _collect_load_feed(
    *,
    feed: str,
    target_date: date,
    archive_root: Path | None,
    degraded: list[str],
) -> int:
    if feed == "cls":
        collector: Any = ClsNewsCollector(archive_root=archive_root)
    elif feed == "em":
        collector = EmNewsCollector(archive_root=archive_root)
    elif feed == "em_announce":
        collector = EmAnnouncementCollector(archive_root=archive_root)
    else:
        raise ValueError(f"unsupported news feed={feed!r}")

    try:
        batch = await collector.collect(target_date)
    except SourceUnavailableError as exc:
        note = f"news:{feed}: {exc}"
        degraded.append(note)
        print(f"daily_news DEGRADED: {note}")
        return 0
    except Exception as exc:  # noqa: BLE001 — soft-fail for live pipeline
        note = f"news:{feed}: {type(exc).__name__}: {exc}"
        degraded.append(note)
        print(f"daily_news DEGRADED: {note}")
        return 0

    df = NewsNormalizer().normalize(batch)
    print(
        f"daily_news collect feed={feed} source={batch.source} "
        f"rows_raw={batch.row_count} rows_norm={df.height} path={batch.raw_path}"
    )
    if not df.height:
        return 0
    result = NewsLoader().load(
        df,
        source=batch.source,
        raw_path=batch.raw_path,
        target_date=batch.target_date or target_date,
    )
    loaded = result["rows_loaded"]
    rows_loaded = int(loaded) if not isinstance(loaded, list) else len(loaded)
    print(
        f"daily_news loaded feed={feed} batch_id={result['batch_id']} "
        f"rows={rows_loaded} status={result['status']}"
    )
    return rows_loaded


def _extract_and_load(*, limit: int, degraded: list[str]) -> tuple[int, int]:
    try:
        event_loader = EventLoader()
        rows = event_loader.fetch_unextracted_news(limit=limit)
        if not rows:
            print("daily_news extract: no unextracted rows")
            return 0, 0
        extractor = RuleNewsExtractor()
        items = []
        for row in rows:
            extraction = extractor.extract(
                title=str(row["title"]),
                body=row.get("body"),
                announce_type=row.get("announce_type"),
                hint_symbol=row.get("related_symbol"),
            )
            items.append((int(row["news_id"]), row["published_at"], extraction))
        stats = event_loader.load_extractions(
            items,
            extractor_model=EXTRACTOR_MODEL,
            extractor_version=EXTRACTOR_VERSION,
        )
        print(
            f"daily_news extract events={stats['events']} links={stats['links']} "
            f"scanned={len(items)}"
        )
        return int(stats["events"]), int(stats["links"])
    except Exception as exc:  # noqa: BLE001
        note = f"news:extract: {type(exc).__name__}: {exc}"
        degraded.append(note)
        print(f"daily_news DEGRADED: {note}")
        return 0, 0


async def refresh_daily_news_events(
    *,
    as_of: date,
    archive_root: Path | None = None,
    extract_limit: int = 300,
    skip_flash: bool = False,
    skip_announcements: bool = False,
    skip_extract: bool = False,
) -> DailyNewsRefreshResult:
    """Ingest CLS/EM flash + announcements, then rule_v1 extract → event tables.

    Soft-fails into ``degraded`` so the live Gate-1 report chain is not blocked
    by news-source outages.
    """
    degraded: list[str] = []
    news_rows = 0
    announcement_rows = 0

    if not skip_flash:
        news_rows += await _collect_load_feed(
            feed="cls",
            target_date=as_of,
            archive_root=archive_root,
            degraded=degraded,
        )
        news_rows += await _collect_load_feed(
            feed="em",
            target_date=as_of,
            archive_root=archive_root,
            degraded=degraded,
        )

    if not skip_announcements:
        announcement_rows = await _collect_load_feed(
            feed="em_announce",
            target_date=as_of,
            archive_root=archive_root,
            degraded=degraded,
        )

    events = 0
    links = 0
    if not skip_extract:
        events, links = _extract_and_load(limit=extract_limit, degraded=degraded)

    return DailyNewsRefreshResult(
        as_of=as_of,
        news_rows=news_rows,
        announcement_rows=announcement_rows,
        events=events,
        event_links=links,
        degraded=degraded,
    )
