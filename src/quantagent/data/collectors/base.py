"""Collector base contract: fetch + archive only, no interpretation."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quantagent.data.archive.parquet import ParquetArchive
from quantagent.data.contracts import RawBatch
from quantagent.shared.config import get_settings

__all__ = ["Collector", "RawBatch", "RateLimiter"]


class RateLimiter:
    """Simple in-process minimum-interval limiter (cross-process Redis later)."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class Collector(ABC):
    """Fetch raw data and archive it. Must not parse, clean, or judge."""

    source: str
    dataset: str
    rate_limit: float = 0.5

    def __init__(self, archive_root: Path | None = None) -> None:
        root = archive_root if archive_root is not None else get_settings().data_raw_dir
        self._archive = ParquetArchive(Path(root))
        self._limiter = RateLimiter(self.rate_limit)

    def archive_path(self, target_date: date, *, collected_at: datetime | None = None) -> Path:
        return self._archive.path_for(
            source=self.source,
            dataset=self.dataset,
            target_date=target_date,
            collected_at=collected_at,
        )

    @abstractmethod
    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        """Fetch for ``target_date`` (or range via kwargs) and archive raw response."""

    async def _rate_limited(self, fn: Any, /, **kwargs: Any) -> Any:
        await self._limiter.acquire()
        return await asyncio.to_thread(fn, **kwargs)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
