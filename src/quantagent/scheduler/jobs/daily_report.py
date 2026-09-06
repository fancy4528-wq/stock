"""Daily report scheduled job."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from quantagent.reporting.pipeline import run_daily_pipeline


async def daily_report_job(
    *,
    out_dir: Path | str = Path("docs/daily-reports"),
    shadow_dir: Path | str = Path("data/shadow"),
    as_of: date | None = None,
) -> Path:
    """MVP job: synthetic pipeline until live ingest is wired."""
    # Default: previous calendar day (trading-calendar check is P0 calendar later)
    day = as_of or (date.today() - timedelta(days=1))
    path = await run_daily_pipeline(
        as_of=day,
        out_dir=out_dir,
        shadow_dir=shadow_dir,
        synthetic=True,
    )
    print(f"daily_report_job wrote {path}")
    return path
