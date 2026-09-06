"""Load ``config/scheduler/*.yaml`` for APScheduler defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError


class SchedulerCron(BaseModel):
    hour: int = 18
    minute: int = 0


class DailyLiveJobConfig(BaseModel):
    cron: SchedulerCron = Field(default_factory=SchedulerCron)
    out_dir: str = "docs/daily-reports"
    shadow_dir: str = "data/shadow"
    universe: str = "mvp_cn_50"
    price_source: str = "baostock"
    lookback_sessions: int = 3


class SchedulerConfig(BaseModel):
    timezone: str = "Asia/Shanghai"
    market: str = "CN"
    daily_live: DailyLiveJobConfig = Field(default_factory=DailyLiveJobConfig)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    raise ConfigError("Cannot locate repo root containing config/")


def scheduler_config_path(market: str = "CN", *, config_dir: Path | None = None) -> Path:
    root = config_dir or (_repo_root() / "config" / "scheduler")
    code = market.strip().lower()
    path = root / f"{code}.yaml"
    if not path.is_file():
        raise ConfigError(f"Scheduler config not found: {path}")
    return path


@lru_cache
def load_scheduler_config(market: str = "CN") -> SchedulerConfig:
    path = scheduler_config_path(market)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid scheduler config YAML: {path}")
    jobs_raw = raw.get("jobs")
    jobs: dict[str, Any] = jobs_raw if isinstance(jobs_raw, dict) else {}
    daily_raw = raw.get("daily_live") or jobs.get("daily_live") or jobs.get("daily_report") or {}
    if not isinstance(daily_raw, dict):
        daily_raw = {}
    payload = {
        "timezone": raw.get("timezone", "Asia/Shanghai"),
        "market": raw.get("market", market),
        "daily_live": daily_raw,
    }
    return SchedulerConfig.model_validate(payload)
