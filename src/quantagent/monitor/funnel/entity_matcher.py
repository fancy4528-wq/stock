"""Entity alias dictionary matching for L1 (P2b). Zero LLM."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.shared.errors import ConfigError

MatchKind = Literal["entity", "industry"]


class EntityAliasConfig(BaseModel):
    """symbol → aliases; industry name → industry keywords."""

    aliases: dict[str, list[str]] = Field(default_factory=dict)
    industries: dict[str, list[str]] = Field(default_factory=dict)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_entity_aliases(path: str | None = None) -> EntityAliasConfig:
    cfg = Path(path) if path else _config_root() / "monitor" / "entity_aliases.yaml"
    if not cfg.is_file():
        return EntityAliasConfig()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid entity aliases config: {cfg}")
    return EntityAliasConfig.model_validate(raw)


def _contains(text: str, alias: str) -> bool:
    """Substring match; ASCII aliases are case-insensitive."""
    if not alias:
        return False
    if alias.isascii():
        return alias.casefold() in text.casefold()
    return alias in text


class EntityMatcher:
    """Match news text against holding-scoped alias / industry dictionaries."""

    def __init__(self, cfg: EntityAliasConfig | None = None) -> None:
        self.cfg = cfg or load_entity_aliases()

    def match_entities(
        self,
        text: str,
        holdings: set[str],
        *,
        name_by_symbol: dict[str, str] | None = None,
    ) -> list[str]:
        """Return holding symbols mentioned in ``text`` (stable order by first hit)."""
        if not text or not holdings:
            return []
        names = name_by_symbol or {}
        # (alias, symbol) longer aliases first to prefer specific hits
        pairs: list[tuple[str, str]] = []
        for sym in holdings:
            seen: set[str] = set()
            for alias in self.cfg.aliases.get(sym, []):
                a = (alias or "").strip()
                if a and a not in seen:
                    pairs.append((a, sym))
                    seen.add(a)
            name = (names.get(sym) or "").strip()
            if name and name not in seen:
                pairs.append((name, sym))
                seen.add(name)
        pairs.sort(key=lambda p: len(p[0]), reverse=True)

        hit_order: list[str] = []
        hit_set: set[str] = set()
        for alias, sym in pairs:
            if sym in hit_set:
                continue
            if _contains(text, alias):
                hit_set.add(sym)
                hit_order.append(sym)
        return hit_order

    def match_industries(
        self,
        text: str,
        holdings: set[str],
        *,
        industry_by_symbol: dict[str, str] | None = None,
    ) -> list[str]:
        """Return holdings whose industry keywords appear in ``text``."""
        if not text or not holdings:
            return []
        ind_map = industry_by_symbol or {}
        # industry → keywords (longer first)
        keyed: list[tuple[str, str]] = []  # (keyword, industry)
        for industry, words in self.cfg.industries.items():
            for w in words:
                a = (w or "").strip()
                if a:
                    keyed.append((a, industry))
        keyed.sort(key=lambda p: len(p[0]), reverse=True)

        hit_industries: set[str] = set()
        for keyword, industry in keyed:
            if industry in hit_industries:
                continue
            if _contains(text, keyword):
                hit_industries.add(industry)

        if not hit_industries:
            return []

        out: list[str] = []
        for sym in sorted(holdings):
            ind = (ind_map.get(sym) or "").strip()
            if ind in hit_industries:
                out.append(sym)
        return out

    def match(
        self,
        text: str,
        holdings: set[str],
        *,
        name_by_symbol: dict[str, str] | None = None,
        industry_by_symbol: dict[str, str] | None = None,
    ) -> tuple[list[str], MatchKind | None]:
        """Entity first, then industry. Returns (symbols, kind)."""
        mentioned = self.match_entities(text, holdings, name_by_symbol=name_by_symbol)
        if mentioned:
            return mentioned, "entity"
        mentioned = self.match_industries(
            text, holdings, industry_by_symbol=industry_by_symbol
        )
        if mentioned:
            return mentioned, "industry"
        return [], None
