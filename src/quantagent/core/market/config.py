"""Pydantic MarketConfig + YAML loader (no hard-coded market branches in callers)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError


class Session(BaseModel):
    start: str
    end: str


class PriceLimitRule(BaseModel):
    condition: str
    limit_up: float | None = None
    limit_down: float | None = None


class PriceLimitConfig(BaseModel):
    enabled: bool = True
    rules: list[PriceLimitRule] = Field(default_factory=list)

    def for_security(
        self, *, board: str, is_st: bool = False
    ) -> tuple[float | None, float | None]:
        """Return ``(limit_up, limit_down)`` ratios for the first matching rule.

        ``None`` means no limit (e.g. IPO open days). Ratios are signed the same
        way as ``config/markets/cn.yaml`` (up positive, down negative).
        """
        if not self.enabled:
            return None, None
        for rule in self.rules:
            if _match_limit_condition(rule.condition, board=board, is_st=is_st):
                return rule.limit_up, rule.limit_down
        raise ConfigError(f"No matching price limit rule for board={board!r} is_st={is_st}")


def _match_limit_condition(condition: str, *, board: str, is_st: bool) -> bool:
    """Match a small, explicit subset of condition expressions from market YAML."""
    raw = condition.strip()
    if raw == "default":
        return True
    if raw == "is_st":
        return is_st
    # board == 'star'  /  board == "gem"
    if raw.startswith("board ==") or raw.startswith("board=="):
        token = raw.split("==", 1)[1].strip().strip("'\"")
        return board == token
    # board in ['star','gem']
    if raw.startswith("board in"):
        inside = raw.split("in", 1)[1].strip()
        if inside.startswith("[") and inside.endswith("]"):
            items = [
                part.strip().strip("'\"")
                for part in inside[1:-1].split(",")
                if part.strip()
            ]
            return board in items
    return False


class FeeConfig(BaseModel):
    commission_rate: float = 0.0
    commission_min: float = 0.0
    commission_max: float | None = None
    stamp_duty_buy: float = 0.0
    stamp_duty_sell: float = 0.0
    transfer_fee_rate: float = 0.0
    regulatory_fee_sell: float = 0.0
    other_fee_per_share: float = 0.0


class SlippageConfig(BaseModel):
    model: Literal["fixed_bps", "volume_share", "spread_based"] = "fixed_bps"
    fixed_bps: float = 5.0
    max_volume_share: float = 0.05


class MarketConfig(BaseModel):
    market: Literal["CN", "US", "HK"]
    name: str
    timezone: str
    currency: str

    sessions: list[Session] = Field(default_factory=list)
    has_pre_market: bool = False
    has_post_market: bool = False

    settlement: Literal["T+0", "T+1", "T+2"] = "T+1"
    same_day_sell_allowed: bool = False
    allow_day_trade: bool = False

    price_limit: PriceLimitConfig = Field(default_factory=PriceLimitConfig)
    min_lot_buy: int = 100
    min_lot_buy_by_board: dict[str, int] = Field(default_factory=dict)
    lot_increment_by_board: dict[str, int] = Field(default_factory=dict)
    min_lot_sell: int = 1
    odd_lot_sell_all_at_once: bool = True
    allow_fractional: bool = False

    short_selling_allowed: bool = False
    margin_allowed: bool = False

    fees: FeeConfig = Field(default_factory=FeeConfig)
    slippage: SlippageConfig = Field(default_factory=SlippageConfig)

    industry_taxonomy: str = "sw_2021"
    has_theme_sectors: bool = False

    calendar_source: str = "akshare"
    benchmark_symbol: str = "000300.SH"

    def lot_size(self, board: str = "main") -> int:
        return int(self.min_lot_buy_by_board.get(board, self.min_lot_buy))

    def lot_increment(self, board: str = "main") -> int:
        return int(self.lot_increment_by_board.get(board, self.min_lot_buy))

    def price_limits(
        self, *, board: str, is_st: bool = False
    ) -> tuple[float | None, float | None]:
        return self.price_limit.for_security(board=board, is_st=is_st)

    def estimate_fees(self, *, side: str, notional: float, quantity: float) -> float:
        """Commission + stamp + transfer for one fill (CN-style)."""
        commission = max(notional * self.fees.commission_rate, self.fees.commission_min)
        if self.fees.commission_max is not None:
            commission = min(commission, self.fees.commission_max)
        stamp = 0.0
        if side == "buy":
            stamp = notional * self.fees.stamp_duty_buy
        elif side == "sell":
            stamp = notional * self.fees.stamp_duty_sell
        transfer = notional * self.fees.transfer_fee_rate
        other = quantity * self.fees.other_fee_per_share
        if side == "sell":
            other += notional * self.fees.regulatory_fee_sell
        return float(commission + stamp + transfer + other)


def _repo_root() -> Path:
    # src/quantagent/core/market/config.py → parents[4] = repo root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    raise ConfigError("Cannot locate repo root containing config/")


def market_config_path(market: str, *, config_dir: Path | None = None) -> Path:
    root = config_dir or (_repo_root() / "config" / "markets")
    code = market.strip().lower()
    path = root / f"{code}.yaml"
    if not path.is_file():
        raise ConfigError(f"Market config not found: {path}")
    return path


@lru_cache
def load_market_config(market: str = "CN") -> MarketConfig:
    path = market_config_path(market)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid market config YAML: {path}")
    return MarketConfig.model_validate(raw)
