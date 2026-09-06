"""Scheduler smoke + A4 live pipeline unit tests."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from quantagent.scheduler.app import build_scheduler, run_once
from quantagent.scheduler.config import load_scheduler_config
from quantagent.scheduler.jobs.daily_pipeline import daily_live_pipeline_job


def test_async_scheduler_starts_under_running_loop() -> None:
    """Regression: AsyncIOScheduler.start() needs a running event loop (hang path)."""

    async def _probe() -> bool:
        sched = build_scheduler(synthetic=True)
        sched.start()
        running = bool(sched.running)
        sched.shutdown(wait=False)
        return running

    assert asyncio.run(_probe()) is True


@pytest.mark.asyncio
async def test_run_once_synthetic(tmp_path: Path) -> None:
    out = tmp_path / "reports"
    shadow = tmp_path / "shadow"
    path = await run_once(
        as_of=date(2026, 9, 1),
        out_dir=out,
        shadow_dir=shadow,
        synthetic=True,
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "A股市场日报" in text
    assert (shadow / "shadow_baseline.jsonl").exists()


def test_build_scheduler_registers_live_job() -> None:
    sched = build_scheduler(synthetic=False)
    jobs = sched.get_jobs()
    assert any(j.id == "cn_daily_live" for j in jobs)


def test_load_scheduler_config_cn() -> None:
    cfg = load_scheduler_config("CN")
    assert cfg.timezone == "Asia/Shanghai"
    assert cfg.daily_live.cron.hour == 18
    assert cfg.daily_live.universe == "mvp_cn_50"
    assert cfg.daily_live.price_source == "baostock"
    assert cfg.daily_live.lookback_sessions == 3


@pytest.mark.asyncio
async def test_daily_live_pipeline_chains_refresh_then_report(tmp_path: Path) -> None:
    out = tmp_path / "reports"
    shadow = tmp_path / "shadow"
    report_path = out / "2026-09-04.md"

    fake_refresh = AsyncMock(
        return_value=type(
            "R",
            (),
            {
                "as_of": date(2026, 9, 4),
                "start": date(2026, 9, 2),
                "end": date(2026, 9, 4),
                "price_rows": 10,
                "index_rows": 3,
                "n_seeded": 12,
            },
        )()
    )
    fake_report = AsyncMock(return_value=report_path)

    with (
        patch(
            "quantagent.scheduler.jobs.daily_pipeline.refresh_daily_market_data",
            fake_refresh,
        ),
        patch(
            "quantagent.scheduler.jobs.daily_pipeline.daily_report_job",
            fake_report,
        ),
    ):
        path = await daily_live_pipeline_job(
            out_dir=out,
            shadow_dir=shadow,
            as_of=date(2026, 9, 4),
            skip_ingest=False,
            skip_seed=False,
        )

    assert path == report_path
    fake_refresh.assert_awaited_once()
    fake_report.assert_awaited_once()
    kwargs = fake_report.await_args.kwargs
    assert kwargs["synthetic"] is False
    assert kwargs["as_of"] == date(2026, 9, 4)


@pytest.mark.asyncio
async def test_run_once_live_uses_pipeline(tmp_path: Path) -> None:
    out = tmp_path / "reports"
    shadow = tmp_path / "shadow"
    expected = out / "live.md"

    with patch(
        "quantagent.scheduler.app.daily_live_pipeline_job",
        AsyncMock(return_value=expected),
    ) as mock_pipe:
        path = await run_once(
            as_of=date(2026, 9, 4),
            out_dir=out,
            shadow_dir=shadow,
            synthetic=False,
            skip_ingest=True,
            skip_seed=True,
        )

    assert path == expected
    mock_pipe.assert_awaited_once()
    assert mock_pipe.await_args.kwargs["skip_ingest"] is True
