"""L1 rule filter — entity + keyword, zero LLM (P2b)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from quantagent.monitor.funnel.entity_matcher import EntityAliasConfig, EntityMatcher, MatchKind
from quantagent.monitor.funnel.keywords import KeywordConfig, KeywordSeverity, keyword_severity


@dataclass(frozen=True)
class L1News:
    """Minimal news row for L1 (title required; summary optional)."""

    title: str
    summary: str | None = None
    news_id: int | None = None
    source: str | None = None


class L1Result(BaseModel):
    """L1 decision: drop or pass to L2."""

    passed: bool
    reason: str
    mentioned_symbols: list[str] = Field(default_factory=list)
    severity: KeywordSeverity | None = None
    match_kind: MatchKind | None = None

    @classmethod
    def drop(cls, reason: str) -> L1Result:
        return cls(passed=False, reason=reason)

    @classmethod
    def pass_to_l2(
        cls,
        mentioned: list[str],
        severity: KeywordSeverity,
        *,
        match_kind: MatchKind,
    ) -> L1Result:
        return cls(
            passed=True,
            reason="pass",
            mentioned_symbols=list(mentioned),
            severity=severity,
            match_kind=match_kind,
        )


DropReason = Literal["no_holding_relevance", "low_severity_keywords"]


class L1Filter:
    """Zero-cost filter. Mechanical match only — no understanding, no LLM."""

    def __init__(
        self,
        *,
        entity_cfg: EntityAliasConfig | None = None,
        keyword_cfg: KeywordConfig | None = None,
    ) -> None:
        self._entities = EntityMatcher(entity_cfg)
        self._keywords = keyword_cfg

    def check_news(
        self,
        news: L1News,
        holdings: set[str],
        *,
        name_by_symbol: dict[str, str] | None = None,
        industry_by_symbol: dict[str, str] | None = None,
    ) -> L1Result:
        text = _relevance_text(news)
        mentioned, kind = self._entities.match(
            text,
            holdings,
            name_by_symbol=name_by_symbol,
            industry_by_symbol=industry_by_symbol,
        )
        if not mentioned or kind is None:
            return L1Result.drop("no_holding_relevance")

        severity = keyword_severity(news.title or "", cfg=self._keywords)
        if severity == "none":
            return L1Result.drop("low_severity_keywords")

        return L1Result.pass_to_l2(mentioned, severity, match_kind=kind)


def _relevance_text(news: L1News) -> str:
    parts = [news.title or ""]
    if news.summary:
        parts.append(news.summary)
    return "\n".join(parts)
