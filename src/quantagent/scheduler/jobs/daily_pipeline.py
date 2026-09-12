"""Live daily pipeline: ingest → seed → report/shadow."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quantagent.core.calendar import TradingCalendar
from quantagent.data.ops import refresh_daily_market_data
from quantagent.data.validators.pit import run_pit_checks
from quantagent.scheduler.jobs.daily_report import daily_report_job
from quantagent.shared.alerts import notify_data_quality_fatal, notify_pipeline_fatal
from quantagent.shared.config import get_settings
from quantagent.shared.errors import DataQualityError

_TRANSIENT = (ConnectionError, TimeoutError, OSError)


def _run_pit_checks(*, check_date: date, run_id: str | None, market: str = "CN") -> None:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    rebalance_dates: list[date] | None = None
    cal = TradingCalendar(market)
    if not cal.is_empty():
        # PIT_005: cover last ~24 months of month-end sessions.
        start = date(check_date.year - 2, check_date.month, 1)
        rebalance_dates = cal.month_end_sessions(start, check_date)
    with engine.connect() as conn:
        report = run_pit_checks(
            conn,
            check_date=check_date,
            rebalance_dates=rebalance_dates,
        )
    for result in report.results:
        if result.status == "warn":
            print(f"pit WARN {result.code}: {result.detail}")
        elif result.failed and result.level == "ERROR":
            print(f"pit ERROR {result.code}: {result.detail}")
    if report.has_fatal:
        fatal = next(r for r in report.results if r.failed and r.level == "FATAL")
        notify_data_quality_fatal(fatal.code, fatal.detail, run_id=run_id)
        raise DataQualityError(f"{fatal.code}: {fatal.detail}")


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_TRANSIENT),
)
async def _pipeline_once(
    *,
    out_dir: Path | str,
    shadow_dir: Path | str,
    as_of: date | None,
    universe_code: str,
    market: str,
    price_source: str,
    lookback_sessions: int,
    skip_ingest: bool,
    skip_seed: bool,
) -> Path:
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
        f"daily_live_pipeline refresh as_of={refresh.as_of} run_id={refresh.run_id} "
        f"window=[{refresh.start}, {refresh.end}] "
        f"price_rows={refresh.price_rows} index_rows={refresh.index_rows} "
        f"seeded={refresh.n_seeded}"
    )
    if refresh.degraded:
        for note in refresh.degraded:
            print(f"daily_live_pipeline DEGRADED: {note}")

    if not skip_ingest:
        _run_pit_checks(check_date=refresh.as_of, run_id=refresh.run_id, market=market)

    path = await daily_report_job(
        out_dir=out_dir,
        shadow_dir=shadow_dir,
        as_of=refresh.as_of,
        synthetic=False,
        universe_code=universe_code,
        market=market,
        run_id=refresh.run_id,
        degraded=refresh.degraded or None,
    )
    print(f"daily_live_pipeline wrote {path}")
    return path


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
    """Run Gate-1 live daily chain and return the report path.

    Transient network/IO errors retry up to 3 times. DataQualityError is not
    retried. Any final failure is written to ``data/alerts/fatal.log``.
    """
    try:
        return await _pipeline_once(
            out_dir=out_dir,
            shadow_dir=shadow_dir,
            as_of=as_of,
            universe_code=universe_code,
            market=market,
            price_source=price_source,
            lookback_sessions=lookback_sessions,
            skip_ingest=skip_ingest,
            skip_seed=skip_seed,
        )
    except DataQualityError:
        raise
    except Exception as exc:
        run_id = as_of.strftime("%Y%m%d") + f"-{market.lower()}-daily" if as_of else None
        notify_pipeline_fatal("DAILY_LIVE", str(exc), run_id=run_id)
        raise
