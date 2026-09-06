"""Live daily pipeline: ingest → seed → report/shadow."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from quantagent.data.ops import refresh_daily_market_data
from quantagent.scheduler.jobs.daily_report import daily_report_job


async def daily_live_pipeline_job(
    *,
    out_dir: Path | str = Path("docs/daily-reports"),
    shadow_dir: Path | str = Path("data/shadow"),
    as_of: date | None = None,
    universe_code: str = "mvp_cn_50",
    market: str = "CN",
    price_source: str = "baostock",
    lookback_sessions: int = 3,
    skip_ingest: bool = False,
    skip_seed: bool = False,
) -> Path:
    """Run Gate-1 live daily chain and return the report path."""
    refresh = await refresh_daily_market_data(
        as_of=as_of,
        universe_code=universe_code,
        market=market,
        price_source=price_source,
        lookback_sessions=lookback_sessions,
        skip_ingest=skip_ingest,
        skip_seed=skip_seed,
    )
    print(
        f"daily_live_pipeline refresh as_of={refresh.as_of} "
        f"window=[{refresh.start}, {refresh.end}] "
        f"price_rows={refresh.price_rows} index_rows={refresh.index_rows} "
        f"seeded={refresh.n_seeded}"
    )
    path = await daily_report_job(
        out_dir=out_dir,
        shadow_dir=shadow_dir,
        as_of=refresh.as_of,
        synthetic=False,
        universe_code=universe_code,
        market=market,
    )
    print(f"daily_live_pipeline wrote {path}")
    return path
