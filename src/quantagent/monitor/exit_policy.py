"""User exit policy (stop-loss / take-profit) for P2a price triggers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, model_validator

from quantagent.shared.errors import ConfigError


class StopLossPolicy(BaseModel):
    enabled: bool = True
    type: Literal["fixed", "trailing", "atr"] = "fixed"
    threshold: float = -0.10
    trail_pct: float = 0.15


class TakeProfitStage(BaseModel):
    gain: float
    reduce: float


class TakeProfitPolicy(BaseModel):
    enabled: bool = True
    type: Literal["none", "fixed", "staged", "target_price"] = "staged"
    fixed_gain: float | None = None
    stages: list[TakeProfitStage] = Field(
        default_factory=lambda: [
            TakeProfitStage(gain=0.20, reduce=0.33),
            TakeProfitStage(gain=0.50, reduce=0.50),
        ]
    )


class ExitPolicyBounds(BaseModel):
    stop_loss_min: float = -0.30
    stop_loss_max: float = -0.03


class ExitPolicy(BaseModel):
    """Per-user exit thresholds; system bounds reject unsafe configs."""

    stop_loss: StopLossPolicy = Field(default_factory=StopLossPolicy)
    take_profit: TakeProfitPolicy = Field(default_factory=TakeProfitPolicy)
    bounds: ExitPolicyBounds = Field(default_factory=ExitPolicyBounds)

    @model_validator(mode="after")
    def _validate_bounds(self) -> ExitPolicy:
        if not self.stop_loss.enabled:
            return self
        thr = self.stop_loss.threshold
        lo = self.bounds.stop_loss_min
        hi = self.bounds.stop_loss_max
        if thr < lo or thr > hi:
            raise ConfigError(
                f"stop_loss.threshold={thr} out of bounds [{lo}, {hi}]"
            )
        if self.stop_loss.type == "trailing" and self.stop_loss.trail_pct <= 0:
            raise ConfigError("trailing stop requires trail_pct > 0")
        return self

    def next_take_profit_stage(self, holding_return: float) -> TakeProfitStage | None:
        """First staged level whose gain has been reached (caller tracks fired stages)."""
        if not self.take_profit.enabled or self.take_profit.type != "staged":
            return None
        for stage in sorted(self.take_profit.stages, key=lambda s: s.gain):
            if holding_return >= stage.gain:
                return stage
        return None


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_exit_policy(market: str = "CN") -> ExitPolicy:
    path = _config_root() / "user" / f"exit_policy_{market.strip().lower()}.yaml"
    if not path.is_file():
        raise ConfigError(f"exit policy not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid exit policy: {path}")
    return ExitPolicy.model_validate(raw)
