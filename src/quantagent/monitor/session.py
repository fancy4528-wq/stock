"""CN cash-session helpers for resident monitor loop (P2a)."""

from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError


class SessionWindow(BaseModel):
    start: str = "09:30"
    end: str = "11:30"


class PollBlock(BaseModel):
    interval_seconds: int = 180
    sessions_only: bool = True
    lookback_hours: int = 72


class MonitorSchedule(BaseModel):
    price_snapshot: PollBlock = Field(
        default_factory=lambda: PollBlock(interval_seconds=180, sessions_only=True)
    )
    announcements: PollBlock = Field(
        default_factory=lambda: PollBlock(
            interval_seconds=300, sessions_only=False, lookback_hours=72
        )
    )
    risk_check: PollBlock = Field(
        default_factory=lambda: PollBlock(interval_seconds=300, sessions_only=True)
    )
    timezone: str = "Asia/Shanghai"
    windows: list[SessionWindow] = Field(
        default_factory=lambda: [
            SessionWindow(start="09:30", end="11:30"),
            SessionWindow(start="13:00", end="15:00"),
        ]
    )


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_monitor_schedule(path: str | None = None) -> MonitorSchedule:
    cfg = Path(path) if path else _config_root() / "monitor" / "schedule.yaml"
    if not cfg.is_file():
        return MonitorSchedule()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid monitor schedule: {cfg}")
    polling_raw = raw.get("polling")
    polling: dict[str, Any] = polling_raw if isinstance(polling_raw, dict) else {}
    sessions_raw = raw.get("sessions")
    sessions: dict[str, Any] = sessions_raw if isinstance(sessions_raw, dict) else {}
    windows_raw = sessions.get("windows") or []
    windows = [SessionWindow.model_validate(w) for w in windows_raw] or [
        SessionWindow(start="09:30", end="11:30"),
        SessionWindow(start="13:00", end="15:00"),
    ]
    return MonitorSchedule(
        price_snapshot=PollBlock.model_validate(polling.get("price_snapshot") or {}),
        announcements=PollBlock.model_validate(polling.get("announcements") or {}),
        risk_check=PollBlock.model_validate(polling.get("risk_check") or {}),
        timezone=str(sessions.get("timezone") or "Asia/Shanghai"),
        windows=windows,
    )


def _parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")[:2]
    return time(int(hh), int(mm))


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def is_trading_day(d: date, *, market: str = "CN") -> bool:
    """Prefer DB calendar; fall back to Mon–Fri."""
    try:
        from quantagent.core.calendar import TradingCalendar

        cal = TradingCalendar(market)
        if cal.is_empty():
            return _is_weekday(d)
        return cal.is_trading_day(d)
    except Exception:  # noqa: BLE001
        return _is_weekday(d)


def in_cash_session(
    now: datetime | None = None,
    *,
    schedule: MonitorSchedule | None = None,
    market: str = "CN",
) -> bool:
    """True during CN continuous auction windows on a trading day."""
    sched = schedule or load_monitor_schedule()
    tz = ZoneInfo(sched.timezone)
    when = now or datetime.now(tz)
    if when.tzinfo is None:
        local = when.replace(tzinfo=tz)
    else:
        local = when.astimezone(tz)
    if not is_trading_day(local.date(), market=market):
        return False
    clock = time(local.hour, local.minute, local.second)
    for w in sched.windows:
        start = _parse_hhmm(w.start)
        end = _parse_hhmm(w.end)
        if start <= clock < end:
            return True
    return False
