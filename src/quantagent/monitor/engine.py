"""Monitor once-loop: quotes → triggers → suppress → notify (P2a)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quantagent.monitor.exit_policy import load_exit_policy
from quantagent.monitor.suppression import (
    SuppressionPolicy,
    SuppressionState,
    default_state_path,
    filter_hits,
    load_suppression_policy,
)
from quantagent.monitor.triggers.registry import run_price_triggers
from quantagent.monitor.triggers.risk import evaluate_risk_triggers
from quantagent.monitor.types import QuoteSnapshot, TriggerHit
from quantagent.notify import NotifierAdapter, build_notifier, format_alert
from quantagent.notify.base import DeliveryResult
from quantagent.positions.manual import load_position_book, save_position_book
from quantagent.positions.staleness import check_staleness
from quantagent.positions.types import ManualPositionBook

logger = logging.getLogger(__name__)


@dataclass
class MonitorOnceResult:
    hits_raw: list[TriggerHit]
    hits_sent: list[TriggerHit]
    suppressed: list[tuple[TriggerHit, str]]
    deliveries: list[DeliveryResult] = field(default_factory=list)
    quotes: dict[str, QuoteSnapshot] = field(default_factory=dict)
    stale_note: str | None = None
    notes: list[str] = field(default_factory=list)


def _demo_quotes(book: ManualPositionBook) -> dict[str, QuoteSnapshot]:
    quotes: dict[str, QuoteSnapshot] = {}
    for i, p in enumerate(book.positions):
        if i == 0:
            last = p.avg_cost * 0.88
        elif i == 1:
            last = p.avg_cost * 1.25
        else:
            last = p.avg_cost
        quotes[p.symbol] = QuoteSnapshot(
            symbol=p.symbol,
            name=p.name,
            last=last,
            prev_close=last * 1.01,  # slight daily drop vs prev
            volume=5000 if i == 0 else 1000,
            volume_avg_5d=1000,
            is_limit_down=(i == 0),
        )
    for w in book.watchlist:
        if w.target_price is not None:
            quotes[w.symbol] = QuoteSnapshot(
                symbol=w.symbol,
                name=w.name,
                last=float(w.target_price) * 1.02,
                prev_close=float(w.target_price),
            )
    return quotes


def fetch_quotes_for_book(
    book: ManualPositionBook,
    *,
    demo: bool = False,
) -> tuple[dict[str, QuoteSnapshot], list[str]]:
    notes: list[str] = []
    if demo:
        return _demo_quotes(book), ["demo quotes"]
    from quantagent.data.collectors.akshare.spot import collect_spot_quotes

    try:
        quotes = collect_spot_quotes(book.symbols())
        return quotes, notes
    except Exception as exc:  # noqa: BLE001
        notes.append(f"spot failed: {type(exc).__name__}: {exc}")
        logger.warning("spot collect failed, falling back to demo: %s", exc)
        return _demo_quotes(book), notes + ["fallback demo quotes"]


async def run_monitor_once(
    *,
    positions_path: Path | str,
    market: str = "CN",
    demo: bool = False,
    notify: bool = True,
    notifier: NotifierAdapter | None = None,
    suppression_path: Path | str | None = None,
    policy: SuppressionPolicy | None = None,
    persist_peak_nav: bool = True,
    now: datetime | None = None,
) -> MonitorOnceResult:
    """Single monitor cycle — zero LLM for price + risk path."""
    when = now or datetime.now(UTC)
    path = Path(positions_path)
    book = load_position_book(path)
    stale = check_staleness(book)
    stale_note = stale.message if stale.stale else None

    quotes, notes = fetch_quotes_for_book(book, demo=demo)

    # Update peak_nav for drawdown tracking
    last_map = {s: q.last for s, q in quotes.items() if q.last > 0}
    nav = book.market_value(last_map)
    peak = max(float(book.peak_nav or 0.0), nav)
    if persist_peak_nav and (book.peak_nav is None or peak > float(book.peak_nav)):
        book = book.model_copy(update={"peak_nav": peak})
        save_position_book(book, path)

    price_hits = run_price_triggers(
        book, quotes, policy=load_exit_policy(market), market=market
    )
    risk_hits = evaluate_risk_triggers(book, quotes, market=market)
    raw = [*price_hits, *risk_hits]

    state_path = Path(suppression_path) if suppression_path else default_state_path(book.account)
    state = SuppressionState.load(state_path)
    pol = policy or load_suppression_policy()
    decision = filter_hits(raw, state, pol, now=when)

    deliveries: list[DeliveryResult] = []
    if notify and decision.allowed:
        channel = notifier or build_notifier()
        for hit in decision.allowed:
            alert = format_alert(hit, when=when)
            result = await channel.send(alert)
            deliveries.append(result)
            if result.ok:
                state.record(hit, when=when)
        state.save(state_path)
    elif decision.allowed and not notify:
        for hit in decision.allowed:
            state.record(hit, when=when)
        state.save(state_path)

    return MonitorOnceResult(
        hits_raw=raw,
        hits_sent=list(decision.allowed),
        suppressed=list(decision.suppressed),
        deliveries=deliveries,
        quotes=quotes,
        stale_note=stale_note,
        notes=notes,
    )
