"""Portfolio YAML config."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError


class SelectionConfig(BaseModel):
    top_n: int = 15
    min_score: float = 0.55


class WeightingConfig(BaseModel):
    method: Literal["equal", "score", "rank", "risk_parity"] = "equal"
    max_gross_exposure: float = 0.90
    min_cash: float = 0.10


class RebalanceConfig(BaseModel):
    max_turnover_per_rebalance: float = 0.30


class PortfolioConfig(BaseModel):
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    weighting: WeightingConfig = Field(default_factory=WeightingConfig)
    rebalance: RebalanceConfig = Field(default_factory=RebalanceConfig)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_portfolio_config(market: str = "CN") -> PortfolioConfig:
    path = _config_root() / "portfolio" / f"{market.strip().lower()}.yaml"
    if not path.is_file():
        raise ConfigError(f"Portfolio config not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid portfolio config: {path}")
    return PortfolioConfig.model_validate(raw)
