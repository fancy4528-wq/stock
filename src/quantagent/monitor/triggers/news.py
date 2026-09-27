"""D-class news triggers — L1 entity + keyword filter (P2b). Zero LLM."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from quantagent.monitor.funnel.l1_rules import L1Filter, L1News, L1Result
from quantagent.monitor.types import Severity, TriggerHit


class NewsCooldownConfig(BaseModel):
    critical: float = 12.0
    high: float = 6.0
    medium: float = 4.0


class NewsTriggerConfig(BaseModel):
    cooldown_hours: NewsCooldownConfig = Field(default_factory=NewsCooldownConfig)
    message: str = "{name} 相关新闻[{severity}]：{title_short}"


@dataclass(frozen=True)
class NewsFeedItem:
    """One flash / telegraph row for D-class L1 evaluation."""

    title: str
    summary: str | None = None
    news_id: int | None = None
    published_at: datetime | None = None
    source: str | None = None
    url: str | None = None
    content_hash: str | None = None
    related_symbol: str | None = None


@dataclass(frozen=True)
class NewsL1Stats:
    scanned: int = 0
    passed: int = 0
    drop_no_relevance: int = 0
    drop_low_severity: int = 0

    @property
    def pass_rate(self) -> float:
        if self.scanned <= 0:
            return 0.0
        return self.passed / self.scanned


def _uid(item: NewsFeedItem) -> str:
    if item.news_id is not None:
        return str(item.news_id)
    if item.content_hash:
        return item.content_hash[:12]
    return str(abs(hash(item.title)) % 10_000_000)


def _to_severity(value: str) -> Severity:
    if value in ("critical", "high", "medium"):
        return value  # type: ignore[return-value]
    return "info"


def evaluate_news_triggers(
    items: Sequence[NewsFeedItem],
    holdings: set[str],
    *,
    name_by_symbol: dict[str, str] | None = None,
    industry_by_symbol: dict[str, str] | None = None,
    l1: L1Filter | None = None,
    cfg: NewsTriggerConfig | None = None,
) -> tuple[list[TriggerHit], NewsL1Stats]:
    """Run L1 on flash news; emit TriggerHit for passes (pre-L2)."""
    filter_ = l1 or L1Filter()
    conf = cfg or NewsTriggerConfig()
    names = name_by_symbol or {}
    cool = conf.cooldown_hours

    hits: list[TriggerHit] = []
    drop_rel = 0
    drop_sev = 0
    passed = 0

    for item in items:
        result = filter_.check_news(
            L1News(title=item.title, summary=item.summary, news_id=item.news_id, source=item.source),
            holdings,
            name_by_symbol=names,
            industry_by_symbol=industry_by_symbol,
        )
        if not result.passed:
            if result.reason == "no_holding_relevance":
                drop_rel += 1
            elif result.reason == "low_severity_keywords":
                drop_sev += 1
            continue
        passed += 1
        hits.append(
            _hit_from_pass(item, result, names=names, conf=conf, cool=cool)
        )

    stats = NewsL1Stats(
        scanned=len(items),
        passed=passed,
        drop_no_relevance=drop_rel,
        drop_low_severity=drop_sev,
    )
    return hits, stats


def _hit_from_pass(
    item: NewsFeedItem,
    result: L1Result,
    *,
    names: dict[str, str],
    conf: NewsTriggerConfig,
    cool: NewsCooldownConfig,
) -> TriggerHit:
    sev_raw = result.severity or "medium"
    sev = _to_severity(sev_raw)
    primary = result.mentioned_symbols[0] if result.mentioned_symbols else "_unknown"
    name = names.get(primary) or primary
    title_short = (item.title or "")[:80]
    try:
        message = conf.message.format(
            name=name,
            severity=sev,
            title_short=title_short,
            symbol=primary,
        )
    except (KeyError, ValueError):
        message = f"{name} 相关新闻[{sev}]：{title_short}"

    uid = _uid(item)
    cooldown = float(getattr(cool, sev, 6.0) if sev != "info" else cool.medium)
    evidence: dict[str, Any] = {
        "title": item.title,
        "summary": item.summary,
        "news_id": item.news_id,
        "source": item.source,
        "url": item.url,
        "content_hash": item.content_hash,
        "mentioned_symbols": list(result.mentioned_symbols),
        "match_kind": result.match_kind,
        "l1_severity": sev_raw,
        "published_at": (item.published_at.isoformat() if item.published_at else None),
    }
    return TriggerHit(
        code=f"NEWS_{sev.upper()}/{uid}",
        severity=sev,
        symbol=primary,
        title=f"NEWS_{sev.upper()}",
        message=message,
        analysis_level="L1",
        cost_usd=0.0,
        evidence=evidence,
        cooldown_hours=cooldown,
    )
