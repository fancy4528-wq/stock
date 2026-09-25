"""Position book freshness checks (P2a)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from quantagent.positions.types import ManualPositionBook


@dataclass(frozen=True)
class StalenessResult:
    """Outcome of a freshness check."""

    stale: bool
    as_of: date
    reference: date
    age_calendar_days: int
    age_trading_days: int | None
    max_trading_days: int
    reason: str
    updated_at: datetime | None

    @property
    def message(self) -> str:
        if not self.stale:
            return (
                f"position book fresh: as_of={self.as_of.isoformat()} "
                f"(age={self.age_calendar_days}d calendar"
                + (
                    f", {self.age_trading_days} trading"
                    if self.age_trading_days is not None
                    else ""
                )
                + ")"
            )
        return self.reason


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def check_staleness(
    book: ManualPositionBook,
    *,
    reference: date | None = None,
    max_trading_days: int = 5,
    open_dates: list[date] | None = None,
) -> StalenessResult:
    """Flag books older than ``max_trading_days`` sessions (or calendar fallback).

    Prefer ``book.updated_at`` when present; else ``book.as_of``.
    When ``open_dates`` is provided, age is counted in trading sessions between
    the book date and ``reference``. Otherwise calendar-day heuristic:
    ``max_trading_days * 1.5`` rounded up (weekends).
    """
    ref = reference or date.today()
    stamp = book.updated_at
    book_day = _as_date(stamp) if stamp is not None else book.as_of
    age_cal = max(0, (ref - book_day).days)

    age_td: int | None = None
    if open_dates:
        opens = sorted(d for d in open_dates if book_day < d <= ref)
        age_td = len(opens)
        stale = age_td > max_trading_days
        reason = (
            f"position book stale: {age_td} trading days since "
            f"{book_day.isoformat()} (limit={max_trading_days})"
            if stale
            else "ok"
        )
    else:
        # Calendar fallback when trading calendar not injected (offline).
        cal_limit = int(max_trading_days * 1.5 + 0.999)
        stale = age_cal > cal_limit
        reason = (
            f"position book stale: {age_cal} calendar days since "
            f"{book_day.isoformat()} (limit≈{cal_limit} without calendar)"
            if stale
            else "ok"
        )

    return StalenessResult(
        stale=stale,
        as_of=book.as_of,
        reference=ref,
        age_calendar_days=age_cal,
        age_trading_days=age_td,
        max_trading_days=max_trading_days,
        reason=reason,
        updated_at=stamp,
    )


def remind_if_stale(
    book: ManualPositionBook,
    *,
    reference: date | None = None,
    max_trading_days: int = 5,
    open_dates: list[date] | None = None,
) -> str | None:
    """Return a human reminder string when stale, else ``None``."""
    result = check_staleness(
        book,
        reference=reference,
        max_trading_days=max_trading_days,
        open_dates=open_dates,
    )
    return result.message if result.stale else None


def utc_now() -> datetime:
    return datetime.now(UTC)


def days_ago(n: int, *, reference: date | None = None) -> date:
    ref = reference or date.today()
    return ref - timedelta(days=n)
