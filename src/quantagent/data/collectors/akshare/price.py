"""Akshare daily price collector (unadjusted East Money hist)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.symbol import normalize_symbol, to_raw_digits
from quantagent.shared.config import get_settings
from quantagent.shared.errors import SourceUnavailableError


class AksharePriceCollector(Collector):
    """Collect A-share daily OHLCV via ``ak.stock_zh_a_hist`` (adjust='').

    Archives the vendor DataFrame as-is. Units remain source-native
    (volume: 手, amount: 元, turnover: %). See PriceNormalizer for conversion.
    """

    source = "akshare"
    dataset = "price_daily"

    def __init__(self, archive_root: Path | None = None, *, rate_limit: float | None = None) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().akshare_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        symbols: list[str] = list(kwargs.get("symbols") or [])
        if not symbols:
            raise ValueError("AksharePriceCollector.collect requires symbols=[...]")

        start: date = kwargs.get("start") or target_date
        end: date = kwargs.get("end") or target_date
        if end < start:
            raise ValueError(f"end {end} < start {start}")

        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            digits = to_raw_digits(normalize_symbol(symbol, market="CN"))
            pdf = await self._fetch_hist(digits, start=start, end=end)
            if pdf is None or pdf.height == 0:
                continue
            # Tag request symbol for multi-symbol archives without mutating vendor columns.
            frames.append(pdf.with_columns(pl.lit(digits).alias("_request_symbol")))

        if not frames:
            raise SourceUnavailableError(
                f"akshare returned no rows for {symbols} in [{start}, {end}]"
            )

        raw = pl.concat(frames, how="diagonal_relaxed")
        return self._archive.write(
            raw,
            source=self.source,
            dataset=self.dataset,
            target_date=end,
            meta={
                "symbols": [normalize_symbol(s, market="CN") for s in symbols],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjust": "",
                "interface": "stock_zh_a_hist",
            },
            collected_at=self._now(),
        )

    async def _fetch_hist(self, digits: str, *, start: date, end: date) -> pl.DataFrame:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )
        def _call() -> Any:
            import akshare as ak
            import requests

            apply_proxy_bypass()
            try:
                return ak.stock_zh_a_hist(
                    symbol=digits,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="",
                )
            except requests.exceptions.RequestException as exc:
                # Normalize vendor HTTP failures into retryable OSError subclass.
                raise ConnectionError(str(exc)) from exc

        try:
            pdf = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001 — wrap vendor failures
            raise SourceUnavailableError(
                f"akshare.stock_zh_a_hist failed for {digits}: {exc}"
            ) from exc

        if pdf is None:
            return pl.DataFrame()
        return pl.from_pandas(pdf)
