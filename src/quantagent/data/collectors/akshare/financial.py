"""Akshare / East Money financial statement collector (PIT via NOTICE_DATE)."""

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

_SHEETS = (
    ("profit", "stock_profit_sheet_by_report_em"),
    ("balance", "stock_balance_sheet_by_report_em"),
    ("cashflow", "stock_cash_flow_sheet_by_report_em"),
)


def to_em_symbol(symbol: str) -> str:
    """``600519.SH`` → ``SH600519`` (East Money financial API form)."""
    norm = normalize_symbol(symbol, market="CN")
    digits, exch = norm.split(".")
    return f"{exch}{digits}"


class AkshareFinancialCollector(Collector):
    """Collect profit / balance / cashflow sheets; archive with ``_sheet`` tag.

    Vendor amounts are in 元. ``NOTICE_DATE`` / ``UPDATE_DATE`` drive PIT ``announced_at``.
    """

    source = "akshare"
    dataset = "financial_statement"

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
            raise ValueError("AkshareFinancialCollector.collect requires symbols=[...]")

        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            norm = normalize_symbol(symbol, market="CN")
            em = to_em_symbol(norm)
            for sheet, _iface in _SHEETS:
                pdf = await self._fetch_sheet(em, sheet=sheet)
                if pdf is None or pdf.height == 0:
                    continue
                frames.append(
                    pdf.with_columns(
                        pl.lit(sheet).alias("_sheet"),
                        pl.lit(norm).alias("_request_symbol"),
                    )
                )

        if not frames:
            raise SourceUnavailableError(
                f"akshare financial sheets empty for {symbols}"
            )

        raw = pl.concat(frames, how="diagonal_relaxed")
        return self._archive.write(
            raw,
            source=self.source,
            dataset=self.dataset,
            target_date=target_date,
            meta={
                "symbols": [normalize_symbol(s, market="CN") for s in symbols],
                "interfaces": [i for _, i in _SHEETS],
                "unit": "CNY",
            },
            collected_at=self._now(),
        )

    async def _fetch_sheet(self, em_symbol: str, *, sheet: str) -> pl.DataFrame:
        iface = dict(_SHEETS)[sheet]

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
            fn = getattr(ak, iface)
            try:
                return fn(symbol=em_symbol)
            except requests.exceptions.RequestException as exc:
                raise ConnectionError(str(exc)) from exc

        try:
            pdf = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"akshare.{iface} failed for {em_symbol}: {exc}"
            ) from exc

        if pdf is None:
            return pl.DataFrame()
        return pl.from_pandas(pdf)
