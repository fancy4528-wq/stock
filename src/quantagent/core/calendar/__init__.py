"""Trading calendar service backed by ``trading_calendar`` rows."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import date, timedelta
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from quantagent.shared.config import get_settings
from quantagent.shared.errors import DataError


class TradingCalendar:
    """In-memory open-day index for one market (loaded from Postgres)."""

    def __init__(
        self,
        market: str = "CN",
        *,
        engine: Engine | None = None,
        open_dates: list[date] | None = None,
    ) -> None:
        self.market = market
        if open_dates is not None:
            self._opens = sorted(set(open_dates))
        else:
            eng = engine or create_engine(get_settings().database_url, pool_pre_ping=True)
            self._opens = self._load_opens(eng, market)
        self._open_set = set(self._opens)

    @staticmethod
    def _load_opens(engine: Engine, market: str) -> list[date]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT trade_date
                    FROM trading_calendar
                    WHERE market = :market AND is_open = TRUE
                    ORDER BY trade_date
                    """
                ),
                {"market": market},
            ).fetchall()
        return [r[0] if isinstance(r[0], date) else date.fromisoformat(str(r[0])) for r in rows]

    def __len__(self) -> int:
        return len(self._opens)

    def is_empty(self) -> bool:
        return not self._opens

    def is_trading_day(self, d: date) -> bool:
        return d in self._open_set

    def trading_days(self, start: date, end: date) -> list[date]:
        if end < start:
            return []
        lo = bisect_left(self._opens, start)
        hi = bisect_right(self._opens, end)
        return self._opens[lo:hi]

    def count_trading_days(self, start: date, end: date) -> int:
        return len(self.trading_days(start, end))

    def on_or_before(self, d: date) -> date:
        """Latest open session on or before ``d``."""
        if self.is_empty():
            raise DataError(f"TradingCalendar[{self.market}] is empty; ingest calendar first")
        idx = bisect_right(self._opens, d) - 1
        if idx < 0:
            raise DataError(f"No trading day on or before {d} for {self.market}")
        return self._opens[idx]

    def on_or_after(self, d: date) -> date:
        if self.is_empty():
            raise DataError(f"TradingCalendar[{self.market}] is empty; ingest calendar first")
        idx = bisect_left(self._opens, d)
        if idx >= len(self._opens):
            raise DataError(f"No trading day on or after {d} for {self.market}")
        return self._opens[idx]

    def prev_trading_day(self, d: date, n: int = 1) -> date:
        """N-th open day strictly before ``d``."""
        if n < 1:
            raise ValueError("n must be >= 1")
        if self.is_empty():
            raise DataError(f"TradingCalendar[{self.market}] is empty; ingest calendar first")
        idx = bisect_left(self._opens, d) - n
        if idx < 0:
            raise DataError(f"No prev trading day n={n} before {d} for {self.market}")
        return self._opens[idx]

    def next_trading_day(self, d: date, n: int = 1) -> date:
        """N-th open day strictly after ``d``."""
        if n < 1:
            raise ValueError("n must be >= 1")
        if self.is_empty():
            raise DataError(f"TradingCalendar[{self.market}] is empty; ingest calendar first")
        idx = bisect_right(self._opens, d) + (n - 1)
        if idx >= len(self._opens):
            raise DataError(f"No next trading day n={n} after {d} for {self.market}")
        return self._opens[idx]

    def default_as_of(self, today: date | None = None) -> date:
        """Session date for an after-close daily job.

        If ``today`` is open → ``today``; else last open on or before ``today``.
        Falls back to weekday-yesterday when the DB calendar is empty.
        """
        day = today or date.today()
        if self.is_empty():
            # Mon–Fri heuristic only as last resort before calendar ingest.
            d = day
            for _ in range(10):
                if d.weekday() < 5:
                    return d
                d -= timedelta(days=1)
            return day - timedelta(days=1)
        return self.on_or_before(day)

    def month_end_sessions(self, start: date, end: date) -> list[date]:
        """Last open session on or before each calendar month-end in ``[start, end]``.

        Used as MVP monthly rebalance / ``universe_snapshot`` dates
        (``snapshot_frequency: monthly``). Dedupes when several month-ends
        collapse to the same session.
        """
        if end < start:
            return []
        if self.is_empty():
            raise DataError(f"TradingCalendar[{self.market}] is empty; ingest calendar first")
        out: list[date] = []
        y, m = start.year, start.month
        while True:
            last_day = date(y, m, monthrange(y, m)[1])
            if last_day >= start:
                try:
                    sess = self.on_or_before(last_day)
                except DataError:
                    sess = None
                if sess is not None and start <= sess <= end:
                    if not out or out[-1] != sess:
                        out.append(sess)
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
            if date(y, m, 1) > end:
                break
        return out


@lru_cache
def load_trading_calendar(market: str = "CN") -> TradingCalendar:
    """Cached calendar from DB (clear cache after re-ingest in long processes)."""
    return TradingCalendar(market=market)
