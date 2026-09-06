"""Baostock trading calendar collector (dense is_trading_day flags)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.shared.config import get_settings
from quantagent.shared.errors import SourceUnavailableError

__all__ = ["BaostockCalendarCollector"]


class BaostockCalendarCollector(Collector):
    """Collect CN calendar via ``bs.query_trade_dates``.

    Rows include weekends/holidays with ``is_trading_day`` 0/1. Used as the
    dual-source check against akshare open-day lists.
    """

    source = "baostock"
    dataset = "trading_calendar"

    def __init__(
        self, archive_root: Path | None = None, *, rate_limit: float | None = None
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().baostock_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        start: date = kwargs.get("start") or date(target_date.year - 10, 1, 1)
        end: date = kwargs.get("end") or target_date
        if end < start:
            raise ValueError(f"end {end} < start {start}")

        raw = await self._fetch_range(start=start, end=end)
        if raw.is_empty():
            raise SourceUnavailableError(
                f"baostock.query_trade_dates empty for [{start}, {end}]"
            )

        return self._archive.write(
            raw,
            source=self.source,
            dataset=self.dataset,
            target_date=end,
            meta={
                "market": "CN",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "interface": "query_trade_dates",
            },
            collected_at=self._now(),
        )

    async def _fetch_range(self, *, start: date, end: date) -> pl.DataFrame:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )
        def _call() -> list[dict[str, str]]:
            import baostock as bs  # type: ignore[import-untyped]

            apply_proxy_bypass()
            lg = bs.login()
            if lg.error_code != "0":
                raise ConnectionError(f"baostock login failed: {lg.error_msg}")
            try:
                rs = bs.query_trade_dates(
                    start_date=start.isoformat(), end_date=end.isoformat()
                )
                if rs.error_code != "0":
                    raise ConnectionError(
                        f"baostock.query_trade_dates failed: {rs.error_msg}"
                    )
                rows: list[dict[str, str]] = []
                while rs.error_code == "0" and rs.next():
                    data = rs.get_row_data()
                    rows.append(
                        {
                            "calendar_date": data[0],
                            "is_trading_day": data[1],
                        }
                    )
                return rows
            finally:
                bs.logout()

        try:
            rows = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"baostock.query_trade_dates failed: {exc}"
            ) from exc

        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows)
