"""Keyword severity table for L1 news filter (P2b). Zero LLM."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError

KeywordSeverity = Literal["critical", "high", "medium", "none"]


class KeywordConfig(BaseModel):
    critical: list[str] = Field(default_factory=list)
    high: list[str] = Field(default_factory=list)
    medium: list[str] = Field(default_factory=list)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_keyword_config(path: str | None = None) -> KeywordConfig:
    cfg = Path(path) if path else _config_root() / "monitor" / "keywords.yaml"
    if not cfg.is_file():
        return KeywordConfig()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid keywords config: {cfg}")
    return KeywordConfig.model_validate(raw)


def keyword_severity(
    title: str,
    *,
    cfg: KeywordConfig | None = None,
) -> KeywordSeverity:
    """Return highest matching tier for ``title``; unmatched → ``none``."""
    conf = cfg or load_keyword_config()
    text = title or ""
    if not text:
        return "none"
    for key in sorted(conf.critical, key=len, reverse=True):
        if key and key in text:
            return "critical"
    for key in sorted(conf.high, key=len, reverse=True):
        if key and key in text:
            return "high"
    for key in sorted(conf.medium, key=len, reverse=True):
        if key and key in text:
            return "medium"
    return "none"
