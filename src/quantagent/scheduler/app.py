"""APScheduler entry for P1 daily report job."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from quantagent.scheduler.jobs.daily_report import daily_report_job


def build_scheduler(
    *,
    timezone: str = "Asia/Shanghai",
    hour: int = 18,
    minute: int = 0,
    out_dir: Path | str = Path("docs/daily-reports"),
    shadow_dir: Path | str = Path("data/shadow"),
    synthetic: bool = True,
    universe_code: str = "mvp_cn_50",
) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=timezone)

    async def _job() -> None:
        await daily_report_job(
            out_dir=out_dir,
            shadow_dir=shadow_dir,
            synthetic=synthetic,
            universe_code=universe_code,
        )

    sched.add_job(
        _job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id="cn_daily_report",
        replace_existing=True,
    )
    return sched


async def run_once(
    *,
    as_of: date | None = None,
    out_dir: Path | str = Path("docs/daily-reports"),
    shadow_dir: Path | str = Path("data/shadow"),
    synthetic: bool = True,
    universe_code: str = "mvp_cn_50",
) -> Path:
    return await daily_report_job(
        as_of=as_of,
        out_dir=out_dir,
        shadow_dir=shadow_dir,
        synthetic=synthetic,
        universe_code=universe_code,
    )


def run_scheduler_blocking(**kwargs: Any) -> None:
    """Start scheduler and block (Ctrl+C to stop)."""
    sched = build_scheduler(**kwargs)
    sched.start()
    mode = "synthetic" if kwargs.get("synthetic", True) else "live"
    print(
        f"scheduler started ({mode}): cn_daily_report cron "
        f"{kwargs.get('hour', 18):02d}:{kwargs.get('minute', 0):02d} Asia/Shanghai"
    )
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown(wait=False)
