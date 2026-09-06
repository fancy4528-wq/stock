"""Akshare A-share trading calendar collector (open days)."""

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

__all__ = ["AkshareCalendarCollector"]


class AkshareCalendarCollector(Collector):
    """Collect SSE/SZSE open days via ``ak.tool_trade_date_hist_sina``.

    Vendor frame is a single ``trade_date`` column of open sessions
    (holidays / weekends omitted). Normalizer expands to dense ``is_open``.
    """

    source = "akshare"
    dataset = "trading_calendar"

    def __init__(
        self, archive_root: Path | None = None, *, rate_limit: float | None = None
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().akshare_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        start: date | None = kwargs.get("start")
        end: date | None = kwargs.get("end") or target_date

        raw = await self._fetch_hist()
        if raw.is_empty():
            raise SourceUnavailableError("akshare.tool_trade_date_hist_sina returned empty")

        # Optional clip for smaller archives; full hist is fine for calendar.
        if start is not None or end is not None:
            td = pl.col("trade_date")
            if raw.schema.get("trade_date") == pl.Utf8:
                td = td.str.to_date()
            else:
                td = td.cast(pl.Date)
            framed = raw.with_columns(td.alias("_td"))
            if start is not None:
                framed = framed.filter(pl.col("_td") >= start)
            if end is not None:
                framed = framed.filter(pl.col("_td") <= end)
            raw = framed.drop("_td")
            if raw.is_empty():
                raise SourceUnavailableError(
                    f"akshare calendar empty after clip [{start}, {end}]"
                )

        return self._archive.write(
            raw,
            source=self.source,
            dataset=self.dataset,
            target_date=end or target_date,
            meta={
                "market": "CN",
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "interface": "tool_trade_date_hist_sina",
            },
            collected_at=self._now(),
        )

    async def _fetch_hist(self) -> pl.DataFrame:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )
        def _call() -> Any:
            import akshare as ak  # type: ignore[import-untyped]
            import requests

            apply_proxy_bypass()
            try:
                return ak.tool_trade_date_hist_sina()
            except requests.exceptions.RequestException as exc:
                raise ConnectionError(str(exc)) from exc

        try:
            pdf = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"akshare.tool_trade_date_hist_sina failed: {exc}"
            ) from exc

        if pdf is None:
            return pl.DataFrame()
        return pl.from_pandas(pdf)
