"""Trigger registry — load YAML specs and run A-class price checks."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from quantagent.monitor.exit_policy import ExitPolicy, load_exit_policy
from quantagent.monitor.triggers.base import TriggerSpec, build_holding_metrics
from quantagent.monitor.triggers.price import _DEFAULTS, evaluate_price_triggers
from quantagent.monitor.types import QuoteSnapshot, TriggerHit
from quantagent.positions.types import ManualPositionBook
from quantagent.shared.errors import ConfigError


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent / "config"
    raise ConfigError("Cannot locate config/ directory")


@lru_cache
def load_price_trigger_specs(path: str | None = None) -> dict[str, TriggerSpec]:
    """Load ``config/monitor/price_triggers.yaml``; fall back to code defaults."""
    specs = dict(_DEFAULTS)
    cfg_path = Path(path) if path else _config_root() / "monitor" / "price_triggers.yaml"
    if not cfg_path.is_file():
        return specs
    raw: Any = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    rows = raw.get("triggers") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return specs
    for row in rows:
        if not isinstance(row, dict) or "code" not in row:
            continue
        code = str(row["code"])
        base = specs.get(code)
        specs[code] = TriggerSpec(
            code=code,
            severity=str(row.get("severity", base.severity if base else "medium")),
            message=str(row.get("message", base.message if base else "{name}")),
            cooldown_hours=float(
                row.get("cooldown_hours", base.cooldown_hours if base else 24)
            ),
            enabled=bool(row.get("enabled", True)),
        )
    return specs


def run_price_triggers(
    book: ManualPositionBook,
    quotes: dict[str, QuoteSnapshot] | dict[str, Any],
    *,
    policy: ExitPolicy | None = None,
    market: str = "CN",
    specs: dict[str, TriggerSpec] | None = None,
) -> list[TriggerHit]:
    """Evaluate A-class price triggers for a book + quote map.

    Returns L1 candidates with ``cost_usd=0``. No suppression / notify yet.
    """
    pol = policy or load_exit_policy(market)
    trigger_specs = specs or load_price_trigger_specs()
    normalized: dict[str, QuoteSnapshot] = {}
    for sym, q in quotes.items():
        if isinstance(q, QuoteSnapshot):
            normalized[sym] = q
        else:
            normalized[sym] = QuoteSnapshot.model_validate(q)

    hits: list[TriggerHit] = []
    for metrics in build_holding_metrics(book, normalized):
        hits.extend(evaluate_price_triggers(metrics, pol, trigger_specs))
    return hits
