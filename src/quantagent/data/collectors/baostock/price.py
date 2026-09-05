"""Baostock daily price collector (unadjusted, validation source)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.symbol import normalize_symbol, to_baostock_code
from quantagent.shared.config import get_settings
from quantagent.shared.errors import SourceUnavailableError

_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg,isST"


class BaostockPriceCollector(Collector):
    """Collect A-share daily bars via baostock ``query_history_k_data_plus``.

    ``adjustflag='3'`` = unadjusted. Volume unit is 股; amount is 元.
    Used as the dual-source check against akshare (W2+).
    """

    source = "baostock"
    dataset = "price_daily"

    def __init__(self, archive_root: Path | None = None, *, rate_limit: float | None = None) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().baostock_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        symbols: list[str] = list(kwargs.get("symbols") or [])
        if not symbols:
            raise ValueError("BaostockPriceCollector.collect requires symbols=[...]")

        start: date = kwargs.get("start") or target_date
        end: date = kwargs.get("end") or target_date
        if end < start:
            raise ValueError(f"end {end} < start {start}")

        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            norm = normalize_symbol(symbol, market="CN")
            code = to_baostock_code(norm)
            pdf = await self._fetch_hist(code, start=start, end=end)
            if pdf.height == 0:
                continue
            frames.append(pdf)

        if not frames:
            raise SourceUnavailableError(
                f"baostock returned no rows for {symbols} in [{start}, {end}]"
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
                "adjustflag": "3",
                "interface": "query_history_k_data_plus",
            },
            collected_at=self._now(),
        )

    async def _fetch_hist(self, code: str, *, start: date, end: date) -> pl.DataFrame:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )
        def _call() -> list[dict[str, str]]:
            import baostock as bs

            apply_proxy_bypass()
            lg = bs.login()
            if lg.error_code != "0":
                raise ConnectionError(f"baostock login failed: {lg.error_msg}")
            try:
                rs = bs.query_history_k_data_plus(
                    code,
                    _FIELDS,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    frequency="d",
                    adjustflag="3",
                )
                if rs.error_code != "0":
                    raise ConnectionError(f"baostock query failed: {rs.error_msg}")
                rows: list[dict[str, str]] = []
                while rs.error_code == "0" and rs.next():
                    rows.append(dict(zip(rs.fields, rs.get_row_data(), strict=True)))
                return rows
            finally:
                bs.logout()

        try:
            rows = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"baostock query failed for {code}: {exc}"
            ) from exc

        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows)
