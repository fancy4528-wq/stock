"""Alert suppression: cooldown, daily caps, quiet hours (P2a)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from quantagent.monitor.types import TriggerHit
from quantagent.shared.errors import ConfigError


class QuietWindow(BaseModel):
    start: str = "22:00"  # HH:MM local
    end: str = "08:00"


class SuppressionPolicy(BaseModel):
    max_alerts_per_day: int = 10
    max_critical_per_day: int = 5
    max_alerts_per_symbol_per_day: int = 3
    quiet_hours: list[QuietWindow] = Field(
        default_factory=lambda: [QuietWindow(start="22:00", end="08:00")]
    )
    # critical bypasses quiet hours
    critical_bypasses_quiet: bool = True
    # default cooldown when hit has none
    default_cooldown_hours: float = 24.0


@dataclass
class SuppressionState:
    """Mutable fire log persisted as JSONL / JSON."""

    fires: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> SuppressionState:
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("fires"), list):
            return cls(fires=list(raw["fires"]))
        if isinstance(raw, list):
            return cls(fires=list(raw))
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fires": self.fires}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def record(self, hit: TriggerHit, *, when: datetime) -> None:
        self.fires.append(
            {
                "code": hit.code,
                "symbol": hit.symbol,
                "severity": hit.severity,
                "fired_at": when.astimezone(UTC).isoformat(),
            }
        )


@dataclass(frozen=True)
class SuppressionDecision:
    allowed: list[TriggerHit]
    suppressed: list[tuple[TriggerHit, str]]


def _parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")[:2]
    return time(int(hh), int(mm))


def in_quiet_hours(now: datetime, windows: list[QuietWindow]) -> bool:
    local_t = now.timetz().replace(tzinfo=None) if now.tzinfo else now.time()
    # Compare as naive clock time
    clock = time(local_t.hour, local_t.minute, local_t.second)
    for w in windows:
        start = _parse_hhmm(w.start)
        end = _parse_hhmm(w.end)
        if start <= end:
            if start <= clock < end:
                return True
        else:
            # wraps midnight
            if clock >= start or clock < end:
                return True
    return False


def _day_key(ts: datetime) -> date:
    return ts.astimezone(UTC).date() if ts.tzinfo else ts.date()


def filter_hits(
    hits: list[TriggerHit],
    state: SuppressionState,
    policy: SuppressionPolicy,
    *,
    now: datetime | None = None,
) -> SuppressionDecision:
    """Apply cooldown + daily caps + quiet hours. Mutates nothing until caller records."""
    when = now or datetime.now(UTC)
    today = _day_key(when)
    allowed: list[TriggerHit] = []
    suppressed: list[tuple[TriggerHit, str]] = []

    today_fires = [
        f
        for f in state.fires
        if _day_key(datetime.fromisoformat(str(f["fired_at"]))) == today
    ]
    n_today = len(today_fires)
    n_crit = sum(1 for f in today_fires if f.get("severity") == "critical")
    per_sym: dict[str, int] = {}
    for f in today_fires:
        sym = str(f.get("symbol") or "")
        per_sym[sym] = per_sym.get(sym, 0) + 1

    # Provisional counts for this batch
    batch_today = n_today
    batch_crit = n_crit
    batch_sym = dict(per_sym)

    for hit in hits:
        # Quiet hours
        if in_quiet_hours(when, policy.quiet_hours):
            if not (policy.critical_bypasses_quiet and hit.severity == "critical"):
                suppressed.append((hit, "quiet_hours"))
                continue

        # Cooldown: same code+symbol
        cool_h = hit.cooldown_hours or policy.default_cooldown_hours
        last: datetime | None = None
        for f in state.fires:
            if f.get("code") == hit.code and f.get("symbol") == hit.symbol:
                t = datetime.fromisoformat(str(f["fired_at"]))
                if last is None or t > last:
                    last = t
        if last is not None and when - last < timedelta(hours=cool_h):
            suppressed.append((hit, f"cooldown<{cool_h}h"))
            continue

        # Daily caps
        if batch_today >= policy.max_alerts_per_day:
            suppressed.append((hit, "max_alerts_per_day"))
            continue
        if hit.severity == "critical" and batch_crit >= policy.max_critical_per_day:
            suppressed.append((hit, "max_critical_per_day"))
            continue
        sym_n = batch_sym.get(hit.symbol, 0)
        if sym_n >= policy.max_alerts_per_symbol_per_day:
            suppressed.append((hit, "max_alerts_per_symbol_per_day"))
            continue

        allowed.append(hit)
        batch_today += 1
        batch_sym[hit.symbol] = sym_n + 1
        if hit.severity == "critical":
            batch_crit += 1

    return SuppressionDecision(allowed=allowed, suppressed=suppressed)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_suppression_policy(path: str | None = None) -> SuppressionPolicy:
    cfg = Path(path) if path else _config_root() / "monitor" / "suppression.yaml"
    if not cfg.is_file():
        return SuppressionPolicy()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid suppression config: {cfg}")
    return SuppressionPolicy.model_validate(raw)


def default_state_path(account: str = "manual_cn") -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "data" / "monitor" / f"suppression_{account}.json"
    return Path("data/monitor") / f"suppression_{account}.json"
