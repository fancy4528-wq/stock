"""东财快讯 via akshare ``stock_info_global_em``."""

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

__all__ = ["EmNewsCollector"]


class EmNewsCollector(Collector):
    """Latest East Money finance flash items."""

    source = "em"
    dataset = "news"

    def __init__(
        self, archive_root: Path | None = None, *, rate_limit: float | None = None
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().akshare_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        del kwargs
        df = await self._fetch()
        if df.is_empty():
            raise SourceUnavailableError("akshare.stock_info_global_em returned empty")
        return self._archive.write(
            df,
            source=self.source,
            dataset=self.dataset,
            target_date=target_date,
            meta={"interface": "stock_info_global_em"},
            collected_at=self._now(),
        )

    async def _fetch(self) -> pl.DataFrame:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _call() -> pl.DataFrame:
            apply_proxy_bypass()
            import akshare as ak

            pdf = ak.stock_info_global_em()
            if pdf is None or pdf.empty:
                return pl.DataFrame()
            return pl.from_pandas(pdf)

        return await self._rate_limited(_call)  # type: ignore[no-any-return]
