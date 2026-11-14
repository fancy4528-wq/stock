"""Market-wide shock keywords for L1 (war, election, sanctions). Zero LLM."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError

MarketSeverity = Literal["critical", "high", "medium"]


ShockDirection = Literal["negative", "positive", "unclear"]


class MarketShockRule(BaseModel):
    keyword: str
    severity: MarketSeverity
    direction: ShockDirection = "negative"
    ignore_if: list[str] = Field(default_factory=list)


class MarketShockMatch(BaseModel):
    severity: MarketSeverity
    keyword: str
    direction: ShockDirection


class MarketShockConfig(BaseModel):
    rules: list[MarketShockRule] = Field(default_factory=list)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_market_shock_config(path: str | None = None) -> MarketShockConfig:
    cfg = Path(path) if path else _config_root() / "monitor" / "market_shocks.yaml"
    if not cfg.is_file():
        return MarketShockConfig()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid market shocks config: {cfg}")
    return MarketShockConfig.model_validate(raw)


def match_market_shock(
    title: str,
    *,
    cfg: MarketShockConfig | None = None,
) -> MarketShockMatch | None:
    """Longest keyword in ``title`` wins. ``ignore_if`` drops that keyword only."""
    text = title or ""
    if not text:
        return None
    conf = cfg or load_market_shock_config()
    rules = sorted(conf.rules, key=lambda r: len((r.keyword or "").strip()), reverse=True)
    for rule in rules:
        keyword = (rule.keyword or "").strip()
        if not keyword or keyword not in text:
            continue
        if any(flag and flag in text for flag in rule.ignore_if):
            continue
        return MarketShockMatch(
            severity=rule.severity,
            keyword=keyword,
            direction=rule.direction,
        )
    return None
