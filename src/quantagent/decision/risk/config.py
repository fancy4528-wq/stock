"""Risk YAML config."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError


class PositionLimits(BaseModel):
    max_single_weight: float = 0.10
    max_industry_weight: float = 0.25
    max_gross_exposure: float = 0.90
    min_cash: float = 0.10
    min_names: int = 5
    max_names: int = 20


class LiquidityLimits(BaseModel):
    min_avg_amount_20d: float = 50_000_000.0


class ExclusionFlags(BaseModel):
    reject_st: bool = True
    reject_suspended: bool = True
    reject_limit_up_buy: bool = True


class RiskConfig(BaseModel):
    position: PositionLimits = Field(default_factory=PositionLimits)
    liquidity: LiquidityLimits = Field(default_factory=LiquidityLimits)
    exclusion: ExclusionFlags = Field(default_factory=ExclusionFlags)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_risk_config(market: str = "CN") -> RiskConfig:
    path = _config_root() / "risk" / f"{market.strip().lower()}.yaml"
    if not path.is_file():
        raise ConfigError(f"Risk config not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid risk config: {path}")
    return RiskConfig.model_validate(raw)
