"""Monitor-dedicated budget: daily USD + L3 call caps, L1-only degradation (P2b).

Tracks monitoring spend independently of the research flow. When exhausted,
``allow_l2`` / ``allow_l3`` become False so the engine keeps price/risk/ann
rules (zero LLM) and skips triage / deep analysis.

Does not import ``quantagent.agents`` — TokenBudget remains the pre-call
interceptor inside L2/L3; this module is policy + persistence + telemetry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, field_validator

from quantagent.shared.errors import ConfigError, QuantAgentError

logger = logging.getLogger(__name__)

ExceedAction = Literal["l1_only", "abort"]
LayerName = Literal["l2", "l3"]


class MonitorBudgetExceeded(QuantAgentError):
    """Raised when ``on_exceed=abort`` and a spend / L3 reserve would exceed caps."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MonitorBudgetConfig(BaseModel):
    """Loaded from ``config/monitor/budget.yaml``."""

    daily_usd_limit: float = Field(default=0.30, ge=0.0)
    l3_max_calls_per_day: int = Field(default=10, ge=0)
    on_exceed: ExceedAction = "l1_only"
    timezone: str = "Asia/Shanghai"

    @field_validator("on_exceed", mode="before")
    @classmethod
    def _norm_action(cls, value: object) -> str:
        text = str(value or "l1_only").strip().lower()
        if text not in ("l1_only", "abort"):
            raise ValueError("on_exceed must be l1_only or abort")
        return text


@dataclass
class MonitorBudgetStats:
    """Snapshot for engine notes / tests."""

    day: date
    spent_usd: float = 0.0
    remaining_usd: float = 0.0
    l2_calls: int = 0
    l3_calls: int = 0
    l3_remaining: int = 0
    l1_only: bool = False
    note: str | None = None


@dataclass
class MonitorBudget:
    """In-memory + optional JSON daily usage for the monitor layer."""

    config: MonitorBudgetConfig
    day: date
    spent_usd: float = 0.0
    l2_calls: int = 0
    l3_calls: int = 0
    degradations: list[str] = field(default_factory=list)
    path: Path | None = None

    # ── queries ──────────────────────────────────────────────────────────

    def remaining_usd(self) -> float:
        return max(0.0, float(self.config.daily_usd_limit) - float(self.spent_usd))

    def remaining_l3_calls(self) -> int:
        return max(0, int(self.config.l3_max_calls_per_day) - int(self.l3_calls))

    def is_l1_only(self) -> bool:
        """True when USD or L3 caps leave no room for further LLM work."""
        if self.config.daily_usd_limit <= 0.0:
            return True
        if self.remaining_usd() <= 1e-12:
            return True
        return False

    def allow_l2(self) -> bool:
        """L2 needs residual USD headroom (batch cost > 0)."""
        return not self.is_l1_only()

    def allow_l3(self) -> bool:
        """L3 needs both USD headroom and remaining call quota."""
        if self.is_l1_only():
            return False
        return self.remaining_l3_calls() > 0

    def degradation_reason(self) -> str | None:
        if self.config.daily_usd_limit <= 0.0:
            return "monitor budget daily_usd_limit=0 → l1_only"
        if self.remaining_usd() <= 1e-12:
            return (
                f"monitor USD exhausted "
                f"(spent=${self.spent_usd:.4f} / limit=${self.config.daily_usd_limit:.4f})"
            )
        if self.remaining_l3_calls() <= 0 and self.config.l3_max_calls_per_day > 0:
            return (
                f"monitor L3 call cap reached ({self.l3_calls}/{self.config.l3_max_calls_per_day})"
            )
        return None

    def stats(self) -> MonitorBudgetStats:
        note = None
        if not self.allow_l2():
            note = self.degradation_reason()
        elif not self.allow_l3():
            note = self.degradation_reason()
        return MonitorBudgetStats(
            day=self.day,
            spent_usd=float(self.spent_usd),
            remaining_usd=self.remaining_usd(),
            l2_calls=int(self.l2_calls),
            l3_calls=int(self.l3_calls),
            l3_remaining=self.remaining_l3_calls(),
            l1_only=self.is_l1_only(),
            note=note,
        )

    # ── mutations ────────────────────────────────────────────────────────

    def record_spend(
        self,
        usd: float,
        *,
        layer: LayerName = "l2",
        calls: int = 1,
    ) -> None:
        """Accumulate actual LLM spend; may flip to l1_only and persist.

        ``calls`` increments the L2 counter (L3 call count is via ``reserve_l3``).
        """
        amount = max(0.0, float(usd))
        self._ensure_today()
        if amount > 0.0:
            # Always book actual spend (money already spent); gates are pre-flight.
            self.spent_usd += amount
        if layer == "l2" and calls > 0:
            self.l2_calls += int(calls)
        if amount <= 0.0 and calls <= 0:
            return
        if self.remaining_usd() <= 1e-12:
            self._note_degradation(self.degradation_reason() or "monitor USD exhausted")
        self._save()
        logger.info(
            "monitor budget record layer=%s +$%.4f spent=$%.4f remaining=$%.4f",
            layer,
            amount,
            self.spent_usd,
            self.remaining_usd(),
        )

    def reserve_l3(self) -> bool:
        """Reserve one L3 call. Returns False (or raises) when capped."""
        self._ensure_today()
        if not self.allow_l3():
            reason = self.degradation_reason() or "L3 not allowed"
            self._note_degradation(reason)
            if self.config.on_exceed == "abort":
                raise MonitorBudgetExceeded(reason)
            logger.info("monitor budget L3 denied: %s", reason)
            return False
        self.l3_calls += 1
        if self.remaining_l3_calls() <= 0:
            self._note_degradation(
                f"monitor L3 call cap reached ({self.l3_calls}/{self.config.l3_max_calls_per_day})"
            )
        self._save()
        return True

    def telemetry_line(self) -> str:
        s = self.stats()
        base = (
            f"budget day={s.day.isoformat()} spent=${s.spent_usd:.4f} "
            f"remain=${s.remaining_usd:.4f} l2_calls={s.l2_calls} "
            f"l3={s.l3_calls}/{self.config.l3_max_calls_per_day} "
            f"l1_only={s.l1_only}"
        )
        if s.note:
            return f"{base} note={s.note}"
        return base

    # ── persistence ──────────────────────────────────────────────────────

    def _ensure_today(self) -> None:
        today = _calendar_day(self.config.timezone)
        if self.day != today:
            logger.info(
                "monitor budget day rollover %s → %s (reset counters)",
                self.day,
                today,
            )
            self.day = today
            self.spent_usd = 0.0
            self.l2_calls = 0
            self.l3_calls = 0
            self.degradations = []

    def _note_degradation(self, reason: str) -> None:
        if reason and reason not in self.degradations:
            self.degradations.append(reason)
            logger.warning("monitor budget degradation: %s", reason)

    def _save(self) -> None:
        path = self.path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "day": self.day.isoformat(),
            "spent_usd": float(self.spent_usd),
            "l2_calls": int(self.l2_calls),
            "l3_calls": int(self.l3_calls),
            "degradations": list(self.degradations),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        config: MonitorBudgetConfig | None = None,
    ) -> MonitorBudget:
        cfg = config or load_monitor_budget_config()
        today = _calendar_day(cfg.timezone)
        if not path.is_file():
            return cls(config=cfg, day=today, path=path)
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("monitor budget load failed (%s); starting fresh", exc)
            return cls(config=cfg, day=today, path=path)
        if not isinstance(raw, dict):
            return cls(config=cfg, day=today, path=path)
        stored_day = _parse_day(raw.get("day"), fallback=today)
        if stored_day != today:
            return cls(config=cfg, day=today, path=path)
        return cls(
            config=cfg,
            day=today,
            spent_usd=max(0.0, float(raw.get("spent_usd") or 0.0)),
            l2_calls=max(0, int(raw.get("l2_calls") or 0)),
            l3_calls=max(0, int(raw.get("l3_calls") or 0)),
            degradations=[str(x) for x in (raw.get("degradations") or []) if x],
            path=path,
        )


def _calendar_day(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


def _parse_day(value: object, *, fallback: date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return fallback
    return fallback


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_monitor_budget_config(path: str | None = None) -> MonitorBudgetConfig:
    cfg = Path(path) if path else _config_root() / "monitor" / "budget.yaml"
    if not cfg.is_file():
        return MonitorBudgetConfig()
    raw: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid monitor budget config: {cfg}")
    return MonitorBudgetConfig.model_validate(raw)


def default_budget_path(account: str = "manual_cn") -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "data" / "monitor" / f"budget_{account}.json"
    return Path("data/monitor") / f"budget_{account}.json"


def build_monitor_budget(
    *,
    account: str = "manual_cn",
    path: Path | str | None = None,
    config: MonitorBudgetConfig | None = None,
    persist: bool = True,
) -> MonitorBudget:
    """Factory used by the monitor engine."""
    cfg = config or load_monitor_budget_config()
    if path is not None:
        return MonitorBudget.load(Path(path), config=cfg)
    if persist:
        return MonitorBudget.load(default_budget_path(account), config=cfg)
    return MonitorBudget(config=cfg, day=_calendar_day(cfg.timezone), path=None)


__all__ = [
    "ExceedAction",
    "MonitorBudget",
    "MonitorBudgetConfig",
    "MonitorBudgetExceeded",
    "MonitorBudgetStats",
    "build_monitor_budget",
    "default_budget_path",
    "load_monitor_budget_config",
]
