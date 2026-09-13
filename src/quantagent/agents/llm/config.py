"""Load ``config/llm.yaml`` (tiers + ADR-0010 budget)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError

AllocationName = Literal["daily_research", "monitoring", "news_extraction", "adhoc"]
ExceedAction = Literal["degrade", "l1_only", "skip", "abort"]
TierName = Literal["small", "medium", "large"]


class TierConfig(BaseModel):
    provider: str = "openai_compatible"
    model: str
    base_url: str = "https://api.openai.com/v1"
    max_tokens_out: int = Field(default=2048, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    input_usd_per_1m: float = Field(default=0.0, ge=0.0)
    output_usd_per_1m: float = Field(default=0.0, ge=0.0)


def _default_allocations() -> dict[str, float]:
    return {
        "daily_research": 0.80,
        "monitoring": 0.30,
        "news_extraction": 0.30,
        "adhoc": 0.10,
    }


def _default_on_exceed() -> dict[str, ExceedAction]:
    return {
        "daily_research": "degrade",
        "monitoring": "l1_only",
        "news_extraction": "skip",
        "adhoc": "abort",
    }


class BudgetConfig(BaseModel):
    daily_usd_limit: float = Field(default=1.50, gt=0.0)
    monthly_usd_limit: float = Field(default=40.0, gt=0.0)
    allocations: dict[str, float] = Field(default_factory=_default_allocations)
    on_exceed: dict[str, ExceedAction] = Field(default_factory=_default_on_exceed)
    per_call_max_tokens_in: int = Field(default=30_000, gt=0)
    per_call_max_tokens_out: int = Field(default=4_000, gt=0)


class LLMConfig(BaseModel):
    tiers: dict[str, TierConfig]
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    def tier(self, name: str) -> TierConfig:
        key = name.strip().lower()
        if key not in self.tiers:
            raise ConfigError(f"Unknown LLM tier: {name!r}; known={sorted(self.tiers)}")
        return self.tiers[key]


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    raise ConfigError("Cannot locate repo root containing config/")


def llm_config_path(*, config_dir: Path | None = None) -> Path:
    root = config_dir or (_repo_root() / "config")
    path = root / "llm.yaml"
    if not path.is_file():
        raise ConfigError(f"LLM config not found: {path}")
    return path


@lru_cache
def load_llm_config() -> LLMConfig:
    path = llm_config_path()
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid LLM config YAML: {path}")
    return LLMConfig.model_validate(raw)


def clear_llm_config_cache() -> None:
    load_llm_config.cache_clear()
