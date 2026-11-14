"""Turn market-shock headlines into a macro stance. Does not size positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from quantagent.monitor.funnel.market_shocks import MarketShockConfig, match_market_shock
from quantagent.monitor.triggers.news import NewsCooldownConfig

CN_TZ = ZoneInfo("Asia/Shanghai")
_SESSION_OPEN = time(9, 30)
_RANK = {"critical": 3, "high": 2, "medium": 1}


@dataclass(frozen=True)
class ActiveShock:
    keyword: str
    severity: Literal["critical", "high", "medium"]
    direction: Literal["negative", "positive", "unclear"]
    title: str
    published_at: datetime


@dataclass(frozen=True)
class ShockAssessment:
    """One row per keyword. Stance text is informational; weights stay unchanged."""

    active: list[ActiveShock]
    stance_line: str | None

    @property
    def critical_negative(self) -> list[ActiveShock]:
        return [s for s in self.active if s.severity == "critical" and s.direction == "negative"]

    @property
    def high_negative(self) -> list[ActiveShock]:
        return [s for s in self.active if s.severity == "high" and s.direction == "negative"]


def decision_window_start(
    as_of: date,
    severity: str,
    *,
    cooldowns: NewsCooldownConfig | None = None,
) -> datetime:
    """Pre-open carry uses the monitor cooldown; the as_of session is always in range."""
    cool = cooldowns or NewsCooldownConfig()
    hours = {"critical": cool.critical, "high": cool.high, "medium": cool.medium}[severity]
    open_at = datetime.combine(as_of, _SESSION_OPEN, tzinfo=CN_TZ)
    return open_at - timedelta(hours=float(hours))


def assess_market_shocks(
    items: list[tuple[str, datetime | None]],
    *,
    as_of: date,
    cfg: MarketShockConfig | None = None,
    cooldowns: NewsCooldownConfig | None = None,
) -> ShockAssessment:
    """Dedupe by keyword. Same-day headlines count; earlier ones only inside cooldown."""
    cool = cooldowns or NewsCooldownConfig()
    day_end = datetime.combine(as_of, time(23, 59), tzinfo=CN_TZ)
    chosen: dict[str, ActiveShock] = {}
    for title, published in items:
        text = (title or "").strip()
        if not text:
            continue
        matched = match_market_shock(text, cfg=cfg)
        if matched is None:
            continue
        when = _coerce_ts(published) or datetime.combine(as_of, time(12, 0), tzinfo=CN_TZ)
        if when > day_end:
            continue
        if not _in_window(when, as_of=as_of, severity=matched.severity, cooldowns=cool):
            continue
        shock = ActiveShock(
            keyword=matched.keyword,
            severity=matched.severity,
            direction=matched.direction,
            title=text[:120],
            published_at=when,
        )
        prev = chosen.get(shock.keyword)
        if prev is None or shock.published_at >= prev.published_at:
            chosen[shock.keyword] = shock
    active = sorted(
        chosen.values(),
        key=lambda s: (_RANK[s.severity], s.published_at),
        reverse=True,
    )
    return ShockAssessment(active=active, stance_line=_stance_line(active))


def items_from_payload(payload: dict[str, Any] | None) -> list[tuple[str, datetime | None]]:
    if not isinstance(payload, dict) or not payload.get("available"):
        return []
    out: list[tuple[str, datetime | None]] = []
    for row in payload.get("items") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        out.append((title, _coerce_ts(row.get("published_at"))))
    return out


def regime_after_shocks(
    regime: Literal["risk_on", "risk_off", "neutral", "transition"],
    confidence: float,
    drivers: list[str],
    assessment: ShockAssessment,
) -> tuple[Literal["risk_on", "risk_off", "neutral", "transition"], float, list[str]]:
    """Critical negative shocks force risk_off. High negative shocks cannot stay risk_on."""
    kept = [d for d in drivers if not str(d).startswith("市场冲击[")]
    if assessment.critical_negative:
        lead = assessment.critical_negative[0]
        return "risk_off", max(confidence, 0.62), [_driver(lead), *kept][:6]
    if assessment.high_negative:
        lead = assessment.high_negative[0]
        next_regime = "neutral" if regime == "risk_on" else regime
        next_conf = min(confidence, 0.55) if regime == "risk_on" else confidence
        return next_regime, next_conf, [_driver(lead), *kept][:6]
    return regime, confidence, kept


def external_from_shocks(assessment: ShockAssessment) -> tuple[str, float, str] | None:
    """Return (direction, score, note) for MacroView.external, or None if nothing hit."""
    if not assessment.active:
        return None
    note = "；".join(
        f"{s.keyword}/{s.direction}:{s.title[:24]}" for s in assessment.active[:3]
    )[:200]
    if assessment.critical_negative:
        return "deteriorating", -0.7, note
    if assessment.high_negative:
        return "deteriorating", -0.4, note
    if any(s.direction == "negative" for s in assessment.active):
        return "deteriorating", -0.2, note
    if any(s.direction == "positive" for s in assessment.active):
        return "improving", 0.25, note
    return "stable", 0.0, note


def _driver(shock: ActiveShock) -> str:
    return f"市场冲击[{shock.keyword}]：{shock.title[:40]}"


def _stance_line(active: list[ActiveShock]) -> str | None:
    if not active:
        return None
    critical = [s for s in active if s.severity == "critical" and s.direction == "negative"]
    high = [s for s in active if s.severity == "high" and s.direction == "negative"]
    if critical:
        lead = critical[0]
        advice = "建议偏向防守"
    elif high:
        lead = high[0]
        advice = "建议保持谨慎"
    else:
        lead = active[0]
        if lead.direction == "positive":
            advice = "外部压力缓和"
        elif lead.direction == "unclear":
            advice = "方向不明，仅作观察"
        else:
            advice = "已记录"
    title = lead.title[:60]
    return f"市场冲击：因「{title}」（{lead.keyword}），{advice}；不改变仓位。"


def _in_window(
    when: datetime,
    *,
    as_of: date,
    severity: str,
    cooldowns: NewsCooldownConfig,
) -> bool:
    local = when.astimezone(CN_TZ)
    if local.date() == as_of:
        return True
    return local >= decision_window_start(as_of, severity, cooldowns=cooldowns)


def _coerce_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CN_TZ)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time(12, 0), tzinfo=CN_TZ)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=CN_TZ)
