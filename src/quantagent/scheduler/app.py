"""APScheduler entry for Gate-1 daily live pipeline."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from quantagent.scheduler.config import load_scheduler_config
from quantagent.scheduler.jobs.daily_pipeline import daily_live_pipeline_job
from quantagent.scheduler.jobs.daily_report import daily_report_job


def build_scheduler(
    *,
    timezone: str | None = None,
    hour: int | None = None,
    minute: int | None = None,
    out_dir: Path | str | None = None,
    shadow_dir: Path | str | None = None,
    synthetic: bool = False,
    universe_code: str | None = None,
    market: str = "CN",
    price_source: str | None = None,
    lookback_sessions: int | None = None,
    skip_ingest: bool = False,
    skip_seed: bool = False,
) -> AsyncIOScheduler:
    """Build scheduler that fires every calendar day, then skips non-sessions.

    Live mode (default): ingest → seed → report --live.
    Synthetic mode: report-only demo (no network / DB refresh).
    """
    cfg = load_scheduler_config(market)
    job_cfg = cfg.daily_live
    tz = timezone or cfg.timezone
    hh = hour if hour is not None else job_cfg.cron.hour
    mm = minute if minute is not None else job_cfg.cron.minute
    reports = Path(out_dir) if out_dir is not None else Path(job_cfg.out_dir)
    shadows = Path(shadow_dir) if shadow_dir is not None else Path(job_cfg.shadow_dir)
    universe = universe_code or job_cfg.universe
    src = price_source or job_cfg.price_source
    lookback = lookback_sessions if lookback_sessions is not None else job_cfg.lookback_sessions

    sched = AsyncIOScheduler(timezone=tz)

    async def _job() -> None:
        from quantagent.core.calendar import TradingCalendar

        today = date.today()
        cal = TradingCalendar(market)
        if not cal.is_empty() and not cal.is_trading_day(today):
            print(f"daily_pipeline skip: {today} is not a {market} trading day")
            return
        if cal.is_empty() and today.weekday() >= 5:
            print(
                f"daily_pipeline skip: {today} weekend "
                f"(trading_calendar empty — ingest calendar for holiday awareness)"
            )
            return
        if synthetic:
            await daily_report_job(
                out_dir=reports,
                shadow_dir=shadows,
                synthetic=True,
                universe_code=universe,
                market=market,
            )
            return
        await daily_live_pipeline_job(
            out_dir=reports,
            shadow_dir=shadows,
            universe_code=universe,
            market=market,
            price_source=src,
            lookback_sessions=lookback,
            skip_ingest=skip_ingest,
            skip_seed=skip_seed,
        )

    sched.add_job(
        _job,
        trigger="cron",
        hour=hh,
        minute=mm,
        id="cn_daily_live",
        replace_existing=True,
    )
    return sched


async def run_once(
    *,
    as_of: date | None = None,
    out_dir: Path | str | None = None,
    shadow_dir: Path | str | None = None,
    synthetic: bool = False,
    universe_code: str | None = None,
    market: str = "CN",
    price_source: str | None = None,
    lookback_sessions: int | None = None,
    skip_ingest: bool = False,
    skip_seed: bool = False,
) -> Path:
    """Run one pipeline iteration (does not apply trading-day skip)."""
    cfg = load_scheduler_config(market)
    job_cfg = cfg.daily_live
    reports = Path(out_dir) if out_dir is not None else Path(job_cfg.out_dir)
    shadows = Path(shadow_dir) if shadow_dir is not None else Path(job_cfg.shadow_dir)
    universe = universe_code or job_cfg.universe
    src = price_source or job_cfg.price_source
    lookback = lookback_sessions if lookback_sessions is not None else job_cfg.lookback_sessions

    if synthetic:
        return await daily_report_job(
            as_of=as_of,
            out_dir=reports,
            shadow_dir=shadows,
            synthetic=True,
            universe_code=universe,
            market=market,
        )
    return await daily_live_pipeline_job(
        as_of=as_of,
        out_dir=reports,
        shadow_dir=shadows,
        universe_code=universe,
        market=market,
        price_source=src,
        lookback_sessions=lookback,
        skip_ingest=skip_ingest,
        skip_seed=skip_seed,
    )


def run_scheduler_blocking(**kwargs: Any) -> None:
    """Start scheduler and block (Ctrl+C to stop)."""
    sched = build_scheduler(**kwargs)
    sched.start()
    synthetic = bool(kwargs.get("synthetic", False))
    mode = "synthetic" if synthetic else "live"
    cfg = load_scheduler_config(str(kwargs.get("market", "CN")))
    hh = kwargs.get("hour", cfg.daily_live.cron.hour)
    mm = kwargs.get("minute", cfg.daily_live.cron.minute)
    print(
        f"scheduler started ({mode}): cn_daily_live cron daily "
        f"{hh:02d}:{mm:02d} {cfg.timezone} "
        f"(skips non-trading days via trading_calendar; "
        f"live chain=ingest→seed→report)"
    )
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown(wait=False)
