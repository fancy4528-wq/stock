"""Scheduler smoke tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantagent.scheduler.app import build_scheduler, run_once


@pytest.mark.asyncio
async def test_run_once(tmp_path: Path) -> None:
    out = tmp_path / "reports"
    shadow = tmp_path / "shadow"
    path = await run_once(as_of=date(2026, 9, 1), out_dir=out, shadow_dir=shadow)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "A股市场日报" in text
    assert (shadow / "shadow_baseline.jsonl").exists()


def test_build_scheduler_registers_job() -> None:
    sched = build_scheduler()
    jobs = sched.get_jobs()
    assert any(j.id == "cn_daily_report" for j in jobs)
