"""Baostock index constituent collector (HS300 / ZZ500, dated)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.config import get_settings
from quantagent.shared.errors import SourceUnavailableError

IndexKind = Literal["hs300", "zz500"]


def baostock_code_to_symbol(code: str) -> str:
    """Convert ``sh.600000`` / ``sz.000001`` → ``600000.SH``."""
    return normalize_symbol(str(code).strip(), market="CN")


def _parse_rows(
    rs: Any, *, kind: IndexKind, as_of: date | None
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    while rs.error_code == "0" and rs.next():
        row = rs.get_row_data()
        # Fields: updateDate, code, code_name
        if len(row) < 2:
            continue
        code = str(row[1])
        try:
            symbol = baostock_code_to_symbol(code)
        except ValueError:
            continue
        out.append(
            {
                "update_date": str(row[0]) if row[0] else None,
                "code": code,
                "code_name": str(row[2]) if len(row) > 2 else None,
                "symbol": symbol,
                "index": kind,
                "as_of": None if as_of is None else as_of.isoformat(),
            }
        )
    return out


def _query_once(bs: Any, kind: IndexKind, date_arg: str) -> Any:
    if kind == "hs300":
        return bs.query_hs300_stocks(date=date_arg)
    return bs.query_zz500_stocks(date=date_arg)


class BaostockIndexConstituentCollector(Collector):
    """Fetch dated index membership via ``query_hs300_stocks`` / ``query_zz500_stocks``.

    Prefer :meth:`fetch_symbols_many` for month-end backfills (single login).
    """

    source = "baostock"
    dataset = "index_constituents"

    def __init__(
        self,
        archive_root: Path | None = None,
        *,
        rate_limit: float | None = None,
    ) -> None:
        self.rate_limit = (
            rate_limit if rate_limit is not None else get_settings().baostock_rate_limit
        )
        super().__init__(archive_root=archive_root)

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        kind: IndexKind = kwargs.get("index") or kwargs.get("kind") or "hs300"
        if kind not in ("hs300", "zz500"):
            raise ValueError(f"unsupported index kind: {kind!r}")
        as_of: date | None = kwargs.get("as_of") or kwargs.get("date") or target_date
        rows = await self._fetch_one(kind, as_of=as_of)
        if not rows:
            raise SourceUnavailableError(
                f"baostock {kind} constituents empty as_of={as_of}"
            )
        raw = pl.DataFrame(rows)
        return self._archive.write(
            raw,
            source=self.source,
            dataset=self.dataset,
            target_date=as_of or target_date,
            meta={
                "index": kind,
                "as_of": None if as_of is None else as_of.isoformat(),
                "n": len(rows),
                "interface": (
                    "query_hs300_stocks" if kind == "hs300" else "query_zz500_stocks"
                ),
            },
            collected_at=self._now(),
        )

    async def fetch_symbols(
        self,
        *,
        index: IndexKind = "hs300",
        as_of: date | None = None,
    ) -> list[str]:
        """Return sorted canonical symbols for ``index`` at ``as_of`` (None = latest)."""
        rows = await self._fetch_one(index, as_of=as_of)
        return sorted({str(r["symbol"]) for r in rows if r.get("symbol")})

    async def fetch_symbols_many(
        self,
        as_of_dates: list[date | None],
        *,
        index: IndexKind = "hs300",
    ) -> dict[str, list[str]]:
        """Fetch many as-of dates in **one** baostock login.

        Keys are ``YYYY-MM-DD`` or ``\"latest\"`` when ``as_of`` is None.
        """
        if not as_of_dates:
            return {}

        def _call() -> dict[str, list[str]]:
            import time

            import baostock as bs

            apply_proxy_bypass()
            lg = bs.login()
            if lg.error_code != "0":
                raise ConnectionError(f"baostock login failed: {lg.error_msg}")
            out: dict[str, list[str]] = {}
            n = len(as_of_dates)
            try:
                for i, as_of in enumerate(as_of_dates, 1):
                    key = "latest" if as_of is None else as_of.isoformat()
                    date_arg = "" if as_of is None else as_of.isoformat()
                    rs = _query_once(bs, index, date_arg)
                    if rs.error_code != "0":
                        raise ConnectionError(
                            f"baostock {index} query failed as_of={key}: {rs.error_msg}"
                        )
                    rows = _parse_rows(rs, kind=index, as_of=as_of)
                    out[key] = sorted(
                        {str(r["symbol"]) for r in rows if r.get("symbol")}
                    )
                    print(
                        f"  constituents [{i}/{n}] {key} n={len(out[key])}",
                        flush=True,
                    )
                    if self.rate_limit and self.rate_limit > 0:
                        time.sleep(float(self.rate_limit))
                return out
            finally:
                bs.logout()

        try:
            return await self._rate_limited(_call)
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailableError(
                f"baostock {index} batch constituents failed: {exc}"
            ) from exc

    async def _fetch_one(
        self, kind: IndexKind, *, as_of: date | None
    ) -> list[dict[str, object]]:
        key = "latest" if as_of is None else as_of.isoformat()
        batch = await self.fetch_symbols_many([as_of], index=kind)
        syms = batch.get(key, [])
        return [
            {
                "symbol": s,
                "index": kind,
                "as_of": None if as_of is None else as_of.isoformat(),
            }
            for s in syms
        ]
