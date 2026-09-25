"""Monitor once-loop + resident polling (P2a): quotes/ann → triggers → suppress → notify."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quantagent.monitor.announcements_fetch import fetch_holding_announcements
from quantagent.monitor.exit_policy import load_exit_policy
from quantagent.monitor.session import (
    in_cash_session,
    load_monitor_schedule,
)
from quantagent.monitor.suppression import (
    SuppressionPolicy,
    SuppressionState,
    default_state_path,
    filter_hits,
    load_suppression_policy,
)
from quantagent.monitor.triggers.announcement import (
    AnnouncementItem,
    evaluate_announcement_triggers,
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
    ran_price: bool = False
    ran_risk: bool = False
    ran_announcements: bool = False


@dataclass
class MonitorLoopResult:
    cycles: int
    last: MonitorOnceResult | None = None
    stopped_reason: str = "completed"


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


def _demo_announcements(book: ManualPositionBook) -> list[AnnouncementItem]:
    if not book.positions:
        return []
    p = book.positions[0]
    return [
        AnnouncementItem(
            symbol=p.symbol,
            name=p.name,
            title=f"{p.name or p.symbol} 收到证监会立案调查通知",
            announce_type="立案调查",
            news_id=900001,
            source="em_announce",
        )
    ]


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


def _name_map(book: ManualPositionBook) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in book.positions:
        if p.name:
            out[p.symbol] = p.name
    for w in book.watchlist:
        if w.name:
            out[w.symbol] = w.name
    return out


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
    run_price: bool = True,
    run_risk: bool = True,
    run_announcements: bool = True,
    announcement_items: list[AnnouncementItem] | None = None,
    lookback_hours: int = 72,
) -> MonitorOnceResult:
    """Single monitor cycle — zero LLM for price + risk + announcement path."""
    when = now or datetime.now(UTC)
    path = Path(positions_path)
    book = load_position_book(path)
    stale = check_staleness(book)
    stale_note = stale.message if stale.stale else None
    notes: list[str] = []

    quotes: dict[str, QuoteSnapshot] = {}
    price_hits: list[TriggerHit] = []
    risk_hits: list[TriggerHit] = []
    ann_hits: list[TriggerHit] = []

    if run_price or run_risk:
        quotes, qnotes = fetch_quotes_for_book(book, demo=demo)
        notes.extend(qnotes)
        # Update peak_nav for drawdown tracking
        last_map = {s: q.last for s, q in quotes.items() if q.last > 0}
        nav = book.market_value(last_map)
        peak = max(float(book.peak_nav or 0.0), nav)
        if persist_peak_nav and (book.peak_nav is None or peak > float(book.peak_nav)):
            book = book.model_copy(update={"peak_nav": peak})
            save_position_book(book, path)

        if run_price:
            price_hits = run_price_triggers(
                book, quotes, policy=load_exit_policy(market), market=market
            )
        if run_risk:
            risk_hits = evaluate_risk_triggers(book, quotes, market=market)

    if run_announcements:
        if announcement_items is not None:
            items = announcement_items
        elif demo:
            items = _demo_announcements(book)
            notes.append("demo announcements")
        else:
            items = fetch_holding_announcements(
                book.symbols(), lookback_hours=lookback_hours, now=when
            )
            notes.append(f"announcements fetched={len(items)}")
        ann_hits = evaluate_announcement_triggers(
            items, set(book.symbols()), name_by_symbol=_name_map(book)
        )

    raw = [*price_hits, *risk_hits, *ann_hits]

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
        ran_price=run_price,
        ran_risk=run_risk,
        ran_announcements=run_announcements,
    )


async def run_monitor_loop(
    *,
    positions_path: Path | str,
    market: str = "CN",
    demo: bool = False,
    notify: bool = True,
    notifier: NotifierAdapter | None = None,
    suppression_path: Path | str | None = None,
    max_cycles: int | None = None,
    interval_seconds: float | None = None,
    respect_sessions: bool = True,
    on_cycle: object | None = None,
) -> MonitorLoopResult:
    """Resident P2a loop — each wake runs price/risk (session-gated) + announcements."""
    sched = load_monitor_schedule()
    sleep_s = float(
        interval_seconds if interval_seconds is not None else sched.price_snapshot.interval_seconds
    )
    lookback = int(sched.announcements.lookback_hours)
    cycles = 0
    last_result: MonitorOnceResult | None = None
    reason = "completed"

    try:
        while max_cycles is None or cycles < max_cycles:
            when = datetime.now(UTC)
            in_sess = in_cash_session(when, schedule=sched, market=market)

            if respect_sessions:
                run_price = in_sess or not sched.price_snapshot.sessions_only
                run_risk = in_sess or not sched.risk_check.sessions_only
                run_ann = in_sess or not sched.announcements.sessions_only
            else:
                run_price = True
                run_risk = True
                run_ann = True

            if run_price or run_risk or run_ann:
                last_result = await run_monitor_once(
                    positions_path=positions_path,
                    market=market,
                    demo=demo,
                    notify=notify,
                    notifier=notifier,
                    suppression_path=suppression_path,
                    persist_peak_nav=True,
                    now=when,
                    run_price=run_price,
                    run_risk=run_risk,
                    run_announcements=run_ann,
                    lookback_hours=lookback,
                )
                if callable(on_cycle):
                    on_cycle(cycles + 1, last_result)
            else:
                logger.debug("monitor skip cycle in_session=%s", in_sess)

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            await asyncio.sleep(sleep_s)
    except asyncio.CancelledError:
        reason = "cancelled"
        raise
    except KeyboardInterrupt:
        reason = "keyboard_interrupt"

    return MonitorLoopResult(cycles=cycles, last=last_result, stopped_reason=reason)
