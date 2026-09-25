"""Trigger protocol and evaluation context (P2a)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from quantagent.monitor.exit_policy import ExitPolicy
from quantagent.monitor.types import HoldingMetrics, TriggerHit
from quantagent.positions.types import ManualPositionBook


@runtime_checkable
class PriceTrigger(Protocol):
    """Pure rule trigger — no LLM, no DB."""

    code: str
    severity: str
    cooldown_hours: float

    def evaluate(self, m: HoldingMetrics, policy: ExitPolicy) -> TriggerHit | None: ...


class TriggerSpec:
    """YAML-loaded trigger metadata (message template + cooldown)."""

    def __init__(
        self,
        *,
        code: str,
        severity: str,
        message: str,
        cooldown_hours: float = 24.0,
        enabled: bool = True,
    ) -> None:
        self.code = code
        self.severity = severity
        self.message = message
        self.cooldown_hours = cooldown_hours
        self.enabled = enabled


def format_message(template: str, **kwargs: object) -> str:
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def build_holding_metrics(
    book: ManualPositionBook,
    quotes: Mapping[str, object],
) -> list[HoldingMetrics]:
    """Join positions (+ optional watchlist target) with quotes."""
    from quantagent.monitor.types import QuoteSnapshot

    last_map: dict[str, float] = {}
    for sym, q in quotes.items():
        if isinstance(q, QuoteSnapshot):
            last_map[sym] = float(q.last)
        else:
            last_map[sym] = float(QuoteSnapshot.model_validate(q).last)
    watch_targets = {w.symbol: w.target_price for w in book.watchlist}
    watch_names = {w.symbol: w.name for w in book.watchlist}
    out: list[HoldingMetrics] = []
    for lot in book.positions:
        raw = quotes.get(lot.symbol)
        if raw is None:
            continue
        q = raw if isinstance(raw, QuoteSnapshot) else QuoteSnapshot.model_validate(raw)
        last = float(q.last)
        if lot.entry_high is not None:
            entry_high = float(lot.entry_high)
        else:
            entry_high = max(lot.avg_cost, last)
        entry_high = max(entry_high, last)
        holding_return = last / lot.avg_cost - 1.0 if lot.avg_cost > 0 else 0.0
        dd = last / entry_high - 1.0 if entry_high > 0 else 0.0
        name = lot.name or q.name or lot.symbol
        out.append(
            HoldingMetrics(
                symbol=lot.symbol,
                name=name,
                quantity=lot.quantity,
                avg_cost=lot.avg_cost,
                last=last,
                holding_return=holding_return,
                entry_high=entry_high,
                drawdown_from_entry_high=dd,
                weight=book.weight(lot.symbol, last_map),
                is_limit_up=q.is_limit_up,
                is_limit_down=q.is_limit_down,
                is_suspended=q.is_suspended,
                pct_change=q.pct_change,
                volume_ratio_5d=q.volume_ratio_5d,
                ma60=q.ma60,
                prev_close=q.prev_close,
                prev_ma60=q.prev_ma60,
                target_price=watch_targets.get(lot.symbol),
            )
        )
    # Watchlist-only names for target-price path (no avg_cost → no stop/take profit).
    held = {m.symbol for m in out}
    for w in book.watchlist:
        if w.symbol in held:
            continue
        raw = quotes.get(w.symbol)
        if raw is None:
            continue
        q = raw if isinstance(raw, QuoteSnapshot) else QuoteSnapshot.model_validate(raw)
        name = w.name or watch_names.get(w.symbol) or q.name or w.symbol
        out.append(
            HoldingMetrics(
                symbol=w.symbol,
                name=name,
                quantity=0.0,
                avg_cost=0.0,
                last=float(q.last),
                holding_return=0.0,
                entry_high=float(q.last),
                drawdown_from_entry_high=0.0,
                weight=0.0,
                is_limit_up=q.is_limit_up,
                is_limit_down=q.is_limit_down,
                is_suspended=q.is_suspended,
                pct_change=q.pct_change,
                volume_ratio_5d=q.volume_ratio_5d,
                ma60=q.ma60,
                prev_close=q.prev_close,
                prev_ma60=q.prev_ma60,
                target_price=w.target_price,
            )
        )
    return out
