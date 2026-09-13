"""A-share notices via East Money announcement API (akshare-compatible columns).

akshare.stock_notice_report crashes with ``KeyError: '代码'`` when the day has
zero hits (empty frame, then URL concat). We call the same endpoint and treat
empty as an empty Polars frame, optionally walking back prior calendar days.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.shared.config import get_settings
from quantagent.shared.errors import SourceUnavailableError

__all__ = ["EmAnnouncementCollector", "fetch_em_notice_report"]

_EM_ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_EM_DETAIL = "https://data.eastmoney.com/notices/detail/"
_REPORT_MAP = {
    "全部": "0",
    "财务报告": "1",
    "融资公告": "2",
    "风险提示": "3",
    "信息变更": "4",
    "重大事项": "5",
    "资产重组": "6",
    "持股变动": "7",
}


def fetch_em_notice_report(
    notice_date: date,
    *,
    symbol: str = "全部",
    timeout: float = 30.0,
) -> pl.DataFrame:
    """Fetch one calendar day's CN notices; empty day → empty frame (no crash)."""
    apply_proxy_bypass()
    if symbol not in _REPORT_MAP:
        raise ValueError(f"unsupported notice category: {symbol!r}")

    day_s = notice_date.isoformat()
    params: dict[str, str] = {
        "sr": "-1",
        "page_size": "100",
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "f_node": _REPORT_MAP[symbol],
        "s_node": "0",
        "begin_time": day_s,
        "end_time": day_s,
    }
    first = requests.get(_EM_ANN_URL, params=params, timeout=timeout)
    first.raise_for_status()
    payload = first.json()
    data = payload.get("data") or {}
    total_hits = int(data.get("total_hits") or 0)
    if total_hits <= 0:
        return pl.DataFrame()

    total_page = max(1, math.ceil(total_hits / 100))
    rows: list[dict[str, object]] = []
    for page in range(1, total_page + 1):
        params["page_index"] = str(page)
        if page == 1:
            page_json = payload
        else:
            resp = requests.get(_EM_ANN_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            page_json = resp.json()
        items = (page_json.get("data") or {}).get("list") or []
        for item in items:
            code_info = _pick_code(item.get("codes") or [])
            if code_info is None:
                continue
            columns = item.get("columns") or []
            col_name = ""
            if columns and isinstance(columns[0], dict):
                col_name = str(columns[0].get("column_name") or "")
            stock_code = str(code_info.get("stock_code") or "")
            art_code = str(item.get("art_code") or "")
            title = str(item.get("title") or "")
            notice_raw = item.get("notice_date") or day_s
            notice_d = str(notice_raw)[:10]
            short_name = str(code_info.get("short_name") or "")
            rows.append(
                {
                    "代码": stock_code,
                    "名称": short_name,
                    "公告标题": title,
                    "公告类型": col_name,
                    "公告日期": notice_d,
                    "网址": f"{_EM_DETAIL}{stock_code}/{art_code}.html",
                }
            )

    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows)


def _pick_code(codes: list[Any]) -> dict[str, Any] | None:
    if not codes:
        return None
    if len(codes) == 1 and isinstance(codes[0], dict):
        return codes[0]
    for code in codes:
        if not isinstance(code, dict):
            continue
        ann_type = str(code.get("ann_type") or "")
        if ann_type.startswith("A"):
            return code
    first = codes[0]
    return first if isinstance(first, dict) else None


class EmAnnouncementCollector(Collector):
    """Daily CN announcement list for ``target_date`` (YYYY-MM-DD on vendor)."""

    source = "em_announce"
    dataset = "announcement"

    def __init__(
        self,
        archive_root: Path | None = None,
        *,
        rate_limit: float | None = None,
        fallback_days: int = 7,
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().akshare_rate_limit
        )
        self.fallback_days = max(0, fallback_days)
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        day = kwargs.get("notice_date") or target_date
        if not isinstance(day, date):
            day = date.fromisoformat(str(day)[:10])
        fallback = kwargs.get("fallback_days", self.fallback_days)
        if not isinstance(fallback, int):
            fallback = self.fallback_days

        tried: list[str] = []
        df = pl.DataFrame()
        used = day
        for offset in range(0, fallback + 1):
            candidate = day - timedelta(days=offset)
            tried.append(candidate.isoformat())
            df = await self._fetch(candidate)
            if not df.is_empty():
                used = candidate
                break

        if df.is_empty():
            raise SourceUnavailableError(
                "eastmoney announcement empty for "
                f"{day.isoformat()} (tried {tried}; weekend/holiday with no notices?)"
            )

        return self._archive.write(
            df,
            source=self.source,
            dataset=self.dataset,
            target_date=used,
            meta={
                "interface": "np-anotice-stock.eastmoney.com/api/security/ann",
                "requested_date": day.isoformat(),
                "notice_date": used.isoformat(),
                "fallback_used": used != day,
                "rows": df.height,
            },
            collected_at=self._now(),
        )

    async def _fetch(self, notice_date: date) -> pl.DataFrame:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )
        def _call() -> pl.DataFrame:
            return fetch_em_notice_report(notice_date)

        return await self._rate_limited(_call)  # type: ignore[no-any-return]
