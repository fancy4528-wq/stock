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
    synthetic: bool = True,
    universe_code: str = "mvp_cn_50",
) -> Path:
    """Run daily report pipeline (synthetic demo or live PIT)."""
    # Default: previous calendar day; live path snaps to last trade date in DB
    day = as_of or (date.today() - timedelta(days=1))
    path = await run_daily_pipeline(
        as_of=day,
        out_dir=out_dir,
        shadow_dir=shadow_dir,
        synthetic=synthetic,
        universe_code=universe_code,
    )
    mode = "synthetic" if synthetic else "live"
    print(f"daily_report_job wrote {path} (mode={mode})")
    return path
