"""Akshare Shenwan (申万) industry taxonomy + L1 membership collector."""

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

__all__ = ["AkshareIndustryCollector", "sw_code_digits"]


def sw_code_digits(code: str) -> str:
    """``801010.SI`` / ``801010`` → ``801010``."""
    text = str(code).strip().upper()
    if text.endswith(".SI"):
        text = text[: -len(".SI")]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValueError(f"Invalid SW industry code: {code!r}")
    return digits


class AkshareIndustryCollector(Collector):
    """Collect SW2021 taxonomy (L1–L3) and current L1 constituents.

    Interfaces:
    - ``sw_index_first_info`` / ``sw_index_second_info`` / ``sw_index_third_info``
    - ``index_component_sw`` per L1 code (证券代码 + 计入日期)

    Optional ``symbols=`` filters memberships after fetch (taxonomy always full).
    """

    source = "akshare"
    dataset = "security_industry"

    def __init__(
        self, archive_root: Path | None = None, *, rate_limit: float | None = None
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().akshare_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        filter_symbols: list[str] | None = None
        raw_symbols = kwargs.get("symbols")
        if raw_symbols:
            filter_symbols = [normalize_symbol(s, market="CN") for s in raw_symbols]

        frames: list[pl.DataFrame] = []

        l1 = await self._fetch_taxonomy_level(1)
        if l1.is_empty():
            raise SourceUnavailableError("akshare.sw_index_first_info returned empty")
        frames.append(l1.with_columns(pl.lit("taxonomy_l1").alias("_kind")))

        l2 = await self._fetch_taxonomy_level(2)
        if not l2.is_empty():
            frames.append(l2.with_columns(pl.lit("taxonomy_l2").alias("_kind")))

        l3 = await self._fetch_taxonomy_level(3)
        if not l3.is_empty():
            frames.append(l3.with_columns(pl.lit("taxonomy_l3").alias("_kind")))

        code_col = "行业代码" if "行业代码" in l1.columns else l1.columns[0]
        l1_codes = [
            sw_code_digits(c) for c in l1.get_column(code_col).to_list() if c is not None
        ]
        member_frames: list[pl.DataFrame] = []
        for code in l1_codes:
            cons = await self._fetch_l1_members(code)
            if cons.is_empty():
                continue
            member_frames.append(
                cons.with_columns(
                    pl.lit("member_l1").alias("_kind"),
                    pl.lit(code).alias("_industry_code"),
                )
            )

        if not member_frames:
            raise SourceUnavailableError("akshare index_component_sw returned no L1 members")
        frames.extend(member_frames)

        raw = pl.concat(frames, how="diagonal_relaxed")
        return self._archive.write(
            raw,
            source=self.source,
            dataset=self.dataset,
            target_date=target_date,
            meta={
                "taxonomy": "sw_2021",
                "interfaces": [
                    "sw_index_first_info",
                    "sw_index_second_info",
                    "sw_index_third_info",
                    "index_component_sw",
                ],
                "l1_count": len(l1_codes),
                "filter_symbols": filter_symbols,
            },
            collected_at=self._now(),
        )

    async def _fetch_taxonomy_level(self, level: int) -> pl.DataFrame:
        fn_name = {
            1: "sw_index_first_info",
            2: "sw_index_second_info",
            3: "sw_index_third_info",
        }[level]

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
                return getattr(ak, fn_name)()
            except requests.exceptions.RequestException as exc:
                raise ConnectionError(str(exc)) from exc

        try:
            pdf = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(f"akshare.{fn_name} failed: {exc}") from exc

        if pdf is None:
            return pl.DataFrame()
        return pl.from_pandas(pdf)

    async def _fetch_l1_members(self, industry_code: str) -> pl.DataFrame:
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
                return ak.index_component_sw(symbol=industry_code)
            except requests.exceptions.RequestException as exc:
                raise ConnectionError(str(exc)) from exc

        try:
            pdf = await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"akshare.index_component_sw failed for {industry_code}: {exc}"
            ) from exc

        if pdf is None:
            return pl.DataFrame()
        return pl.from_pandas(pdf)
