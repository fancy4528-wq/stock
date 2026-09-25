"""C-class announcement triggers — pure rules on announce_type / title (P2a)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.monitor.types import Severity, TriggerHit
from quantagent.shared.errors import ConfigError


class AnnouncementTypeConfig(BaseModel):
    critical: list[str] = Field(default_factory=list)
    high: list[str] = Field(default_factory=list)
    prefer_sources: list[str] = Field(default_factory=lambda: ["em_announce"])
    cooldown_hours: dict[str, float] = Field(
        default_factory=lambda: {"critical": 24.0, "high": 12.0}
    )
    message_critical: str = "{name} 公告：{announce_type} — {title_short}"
    message_high: str = "{name} 公告：{announce_type} — {title_short}"


@dataclass(frozen=True)
class AnnouncementItem:
    """One filing / notice row for C-class evaluation."""

    symbol: str
    title: str
    announce_type: str | None = None
    news_id: int | None = None
    published_at: datetime | None = None
    source: str | None = None
    url: str | None = None
    name: str | None = None


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_announcement_type_config(path: str | None = None) -> AnnouncementTypeConfig:
    cfg = Path(path) if path else _config_root() / "monitor" / "announcement_types.yaml"
    if not cfg.is_file():
        return AnnouncementTypeConfig()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid announcement types config: {cfg}")
    return AnnouncementTypeConfig.model_validate(raw)


def match_announcement_severity(
    *,
    announce_type: str | None,
    title: str,
    cfg: AnnouncementTypeConfig | None = None,
) -> Severity | None:
    """Return severity if critical/high keyword hits type or title (longer first)."""
    conf = cfg or load_announcement_type_config()
    blob = f"{announce_type or ''} {title or ''}"
    for key in sorted(conf.critical, key=len, reverse=True):
        if key and key in blob:
            return "critical"
    for key in sorted(conf.high, key=len, reverse=True):
        if key and key in blob:
            return "high"
    return None


def _uid(item: AnnouncementItem) -> str:
    if item.news_id is not None:
        return str(item.news_id)
    # Stable-ish fallback when no DB id (tests / live scrape without load)
    return str(abs(hash((item.symbol, item.title))) % 10_000_000)


def evaluate_announcement_triggers(
    items: Sequence[AnnouncementItem],
    holdings: set[str],
    *,
    name_by_symbol: dict[str, str] | None = None,
    cfg: AnnouncementTypeConfig | None = None,
) -> list[TriggerHit]:
    """Fire C-class hits for holdings/watchlist symbols only."""
    conf = cfg or load_announcement_type_config()
    names = name_by_symbol or {}
    hits: list[TriggerHit] = []
    for item in items:
        if item.symbol not in holdings:
            continue
        sev = match_announcement_severity(
            announce_type=item.announce_type, title=item.title, cfg=conf
        )
        if sev is None:
            continue
        # Prefer filings; still allow keyword hits on other sources
        prefer = {s.lower() for s in conf.prefer_sources}
        src = (item.source or "").lower()
        if prefer and src and src not in prefer and not item.announce_type:
            # flash without announce_type — skip unless we already matched (keyword in title)
            # Keep matched title keywords (sev is set); only skip empty-type non-prefer when
            # we want filings only — design allows title match, so continue.
            pass

        atype = (item.announce_type or "公告").strip() or "公告"
        title_short = (item.title or "")[:80]
        name = names.get(item.symbol) or item.name or item.symbol
        tmpl = conf.message_critical if sev == "critical" else conf.message_high
        try:
            message = tmpl.format(
                name=name,
                announce_type=atype,
                title_short=title_short,
                symbol=item.symbol,
            )
        except (KeyError, ValueError):
            message = f"{name} 公告：{atype} — {title_short}"

        uid = _uid(item)
        code = f"ANN_{sev.upper()}/{uid}"
        cool = float(conf.cooldown_hours.get(sev, 24.0))
        hits.append(
            TriggerHit(
                code=code,
                severity=sev,
                symbol=item.symbol,
                title=f"ANN_{sev.upper()}",
                message=message,
                analysis_level="L1",
                cost_usd=0.0,
                evidence={
                    "announce_type": atype,
                    "title": item.title,
                    "news_id": item.news_id,
                    "source": item.source,
                    "url": item.url,
                    "published_at": (item.published_at.isoformat() if item.published_at else None),
                },
                cooldown_hours=cool,
            )
        )
    return hits
