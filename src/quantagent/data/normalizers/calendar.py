"""Normalize vendor trading calendars to ``trading_calendar`` rows."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.shared.errors import DataError

CANONICAL_CALENDAR_COLUMNS = [
    "market",
    "trade_date",
    "is_open",
    "prev_trade_date",
    "next_trade_date",
    "note",
    "source",
]


def _parse_date_series(series: pl.Series) -> list[date]:
    out: list[date] = []
    for v in series.to_list():
        if v is None:
            continue
        if isinstance(v, date):
            out.append(v)
        else:
            out.append(date.fromisoformat(str(v)[:10]))
    return out


def attach_prev_next(open_dates: list[date]) -> dict[date, tuple[date | None, date | None]]:
    """Map each open date → (prev_open, next_open)."""
    ordered = sorted(set(open_dates))
    mapping: dict[date, tuple[date | None, date | None]] = {}
    for i, d in enumerate(ordered):
        prev_d = ordered[i - 1] if i > 0 else None
        next_d = ordered[i + 1] if i + 1 < len(ordered) else None
        mapping[d] = (prev_d, next_d)
    return mapping


def expand_dense_calendar(
    open_dates: list[date],
    *,
    market: str,
    source: str,
    start: date | None = None,
    end: date | None = None,
) -> pl.DataFrame:
    """Expand open-day list into dense daily rows with ``is_open`` + neighbors."""
    if not open_dates:
        raise DataError("Cannot expand empty open-date list")
    opens = sorted(set(open_dates))
    lo = start or opens[0]
    hi = end or opens[-1]
    if hi < lo:
        raise DataError(f"calendar end {hi} < start {lo}")

    neighbors = attach_prev_next(opens)
    open_set = set(opens)

    # Carry prev/next for closed days: last open before / first open after.
    rows: list[dict[str, object]] = []
    cur = lo
    # Running pointers for closed days
    open_idx = 0
    while cur <= hi:
        is_open = cur in open_set
        if is_open:
            prev_d, next_d = neighbors[cur]
            # advance open_idx to current
            while open_idx < len(opens) and opens[open_idx] < cur:
                open_idx += 1
        else:
            # largest open < cur
            while open_idx < len(opens) and opens[open_idx] < cur:
                open_idx += 1
            prev_d = opens[open_idx - 1] if open_idx > 0 else None
            next_d = opens[open_idx] if open_idx < len(opens) else None
        rows.append(
            {
                "market": market,
                "trade_date": cur,
                "is_open": is_open,
                "prev_trade_date": prev_d,
                "next_trade_date": next_d,
                "note": None,
                "source": source,
            }
        )
        cur += timedelta(days=1)
    return pl.DataFrame(rows).select(CANONICAL_CALENDAR_COLUMNS)


class CalendarNormalizer:
    """Map akshare / baostock calendar archives → canonical rows."""

    def normalize(
        self,
        batch: RawBatch,
        df: pl.DataFrame | None = None,
        *,
        start: date | None = None,
        end: date | None = None,
        market: str = "CN",
    ) -> pl.DataFrame:
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        meta_start = batch.meta.get("start")
        meta_end = batch.meta.get("end")
        clip_start = start or (date.fromisoformat(meta_start) if meta_start else None)
        clip_end = end or (date.fromisoformat(meta_end) if meta_end else None)

        if batch.source == "akshare":
            return self._normalize_akshare(
                frame, market=market, source=batch.source, start=clip_start, end=clip_end
            )
        if batch.source == "baostock":
            return self._normalize_baostock(
                frame, market=market, source=batch.source, start=clip_start, end=clip_end
            )
        raise DataError(f"No calendar normalizer for source={batch.source!r}")

    def normalize_from_archive(
        self,
        raw_path: Path,
        *,
        start: date | None = None,
        end: date | None = None,
        market: str = "CN",
    ) -> pl.DataFrame:
        df, batch = load_raw_batch(raw_path)
        return self.normalize(batch, df, start=start, end=end, market=market)

    def _normalize_akshare(
        self,
        df: pl.DataFrame,
        *,
        market: str,
        source: str,
        start: date | None,
        end: date | None,
    ) -> pl.DataFrame:
        if "trade_date" not in df.columns:
            raise DataError("akshare calendar missing trade_date column")
        opens = _parse_date_series(df.get_column("trade_date"))
        if start is not None:
            opens = [d for d in opens if d >= start]
        if end is not None:
            opens = [d for d in opens if d <= end]
        return expand_dense_calendar(
            opens, market=market, source=source, start=start, end=end
        )

    def _normalize_baostock(
        self,
        df: pl.DataFrame,
        *,
        market: str,
        source: str,
        start: date | None,
        end: date | None,
    ) -> pl.DataFrame:
        cols = set(df.columns)
        if "calendar_date" not in cols or "is_trading_day" not in cols:
            raise DataError(
                "baostock calendar requires calendar_date + is_trading_day columns"
            )
        dates = _parse_date_series(df.get_column("calendar_date"))
        flags = [
            str(v).strip() in {"1", "1.0", "true", "True"}
            for v in df.get_column("is_trading_day").to_list()
        ]
        opens = [d for d, flag in zip(dates, flags, strict=True) if flag]
        if start is not None:
            opens = [d for d in opens if d >= start]
        if end is not None:
            opens = [d for d in opens if d <= end]
        # Prefer vendor dense range when no explicit clip
        dense_start = start or (min(dates) if dates else None)
        dense_end = end or (max(dates) if dates else None)
        return expand_dense_calendar(
            opens, market=market, source=source, start=dense_start, end=dense_end
        )


def open_dates(df: pl.DataFrame) -> set[date]:
    """Extract open trade dates from a canonical calendar frame."""
    if df.is_empty():
        return set()
    opened = df.filter(pl.col("is_open"))
    return set(_parse_date_series(opened.get_column("trade_date")))
