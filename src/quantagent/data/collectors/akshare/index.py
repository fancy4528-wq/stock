"""Akshare CSI / A-share index daily collector."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.config import get_settings
from quantagent.shared.errors import SourceUnavailableError


def to_sina_index_symbol(symbol: str) -> str:
    """``000300.SH`` → ``sh000300`` (Sina index daily form used by akshare)."""
    norm = normalize_symbol(symbol, market="CN")
    digits, exch = norm.split(".")
    return f"{exch.lower()}{digits}"


class AkshareIndexCollector(Collector):
    """Collect index OHLCV via ``ak.stock_zh_index_daily``.

    Volume is vendor-native (股). No amount column from this interface.
    """

    source = "akshare"
    dataset = "price_daily"

    def __init__(
        self, archive_root: Path | None = None, *, rate_limit: float | None = None
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().akshare_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        symbols: list[str] = list(kwargs.get("symbols") or [])
        if not symbols:
            raise ValueError("AkshareIndexCollector.collect requires symbols=[...]")

        start: date = kwargs.get("start") or date(2000, 1, 1)
        end: date = kwargs.get("end") or target_date
        if end < start:
            raise ValueError(f"end {end} < start {start}")

        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            norm = normalize_symbol(symbol, market="CN")
            sina = to_sina_index_symbol(norm)
            pdf = await self._fetch_index(sina)
            if pdf is None or pdf.height == 0:
                continue
            filtered = pdf.filter(
                (pl.col("date").cast(pl.Date) >= start) & (pl.col("date").cast(pl.Date) <= end)
            )
            if filtered.height == 0:
                continue
            frames.append(
                filtered.with_columns(pl.lit(norm).alias("_request_symbol"))
            )

        if not frames:
            raise SourceUnavailableError(
                f"akshare index returned no rows for {symbols} in [{start}, {end}]"
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
                "interface": "stock_zh_index_daily",
                "kind": "index",
            },
            collected_at=self._now(),
        )

    async def _fetch_index(self, sina_symbol: str) -> pl.DataFrame:
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
                return ak.stock_zh_index_daily(symbol=sina_symbol)
            except requests.exceptions.RequestException as exc:
                raise ConnectionError(str(exc)) from exc

        try:
            pdf = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"akshare.stock_zh_index_daily failed for {sina_symbol}: {exc}"
            ) from exc

        if pdf is None:
            return pl.DataFrame()
        return pl.from_pandas(pdf)
