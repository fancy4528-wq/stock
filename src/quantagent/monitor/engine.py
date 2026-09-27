"""Monitor once-loop + resident polling: quotes/ann/news → triggers → suppress → notify."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.client import LLMClient
from quantagent.agents.llm.config import load_llm_config
from quantagent.monitor.announcements_fetch import fetch_holding_announcements
from quantagent.monitor.budget import MonitorBudget, build_monitor_budget
from quantagent.monitor.cache import AnalysisCache, build_analysis_cache
from quantagent.monitor.exit_policy import load_exit_policy
from quantagent.monitor.funnel.l2_triage import refine_news_hits_with_l2
from quantagent.monitor.news_fetch import fetch_monitor_news
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
from quantagent.monitor.triggers.news import NewsFeedItem, evaluate_news_triggers
from quantagent.monitor.triggers.registry import run_price_triggers
from quantagent.monitor.triggers.risk import evaluate_risk_triggers
from quantagent.monitor.types import QuoteSnapshot, TriggerHit
from quantagent.notify.base import DeliveryResult, NotifierAdapter
from quantagent.notify.factory import build_notifier
from quantagent.notify.formatter import format_alert
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
    ran_news: bool = False
    ran_l2: bool = False
    news_scanned: int = 0
    news_l1_passed: int = 0
    news_l2_relevant: int = 0
    news_l2_mode: str | None = None
    news_l2_cost_usd: float = 0.0
    news_l2_cache_hits: int = 0
    news_l2_cache_misses: int = 0
    budget_spent_usd: float = 0.0
    budget_remaining_usd: float = 0.0
    budget_l1_only: bool = False
    budget_l3_remaining: int = 0
    budget_note: str | None = None


@dataclass
class MonitorLoopResult:
    cycles: int
    last: MonitorOnceResult | None = None
    stopped_reason: str = "completed"


def token_budget_for_monitor(monitor: MonitorBudget) -> TokenBudget:
    """TokenBudget whose ``monitoring`` pool equals residual monitor USD today."""
    llm = load_llm_config()
    remaining = monitor.remaining_usd()
    allocations = dict(llm.budget.allocations)
    allocations["monitoring"] = remaining
    on_exceed = dict(llm.budget.on_exceed)
    on_exceed["monitoring"] = "l1_only" if monitor.config.on_exceed == "l1_only" else "abort"
    budget_cfg = llm.budget.model_copy(update={"allocations": allocations, "on_exceed": on_exceed})
    return TokenBudget(budget=budget_cfg, llm_config=llm, day=monitor.day)


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


def _demo_news(book: ManualPositionBook) -> list[NewsFeedItem]:
    """Synthetic flash items: one L1 pass, one irrelevant drop."""
    if not book.positions:
        return []
    p = book.positions[0]
    name = p.name or p.symbol
    return [
        NewsFeedItem(
            title=f"{name}签署重大合同 金额超预期",
            summary=f"{name}与下游客户签订重大合同",
            news_id=910001,
            source="cls",
            content_hash="demo-news-pass",
        ),
        NewsFeedItem(
            title="某科技公司发布新产品规划",
            summary="与持仓无关的噪音快讯",
            news_id=910002,
            source="cls",
            content_hash="demo-news-drop",
        ),
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


def _industry_map(book: ManualPositionBook) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in book.positions:
        if p.industry:
            out[p.symbol] = p.industry
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
    run_news: bool = True,
    run_l2: bool = True,
    announcement_items: list[AnnouncementItem] | None = None,
    news_items: list[NewsFeedItem] | None = None,
    lookback_hours: int = 72,
    news_lookback_hours: int = 24,
    llm: LLMClient | None = None,
    budget: TokenBudget | None = None,
    monitor_budget: MonitorBudget | None = None,
    analysis_cache: AnalysisCache | None = None,
    cache_path: Path | str | None = None,
    budget_path: Path | str | None = None,
) -> MonitorOnceResult:
    """Single monitor cycle — price/risk/ann L1; news L1 then optional L2 triage."""
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
    news_hits: list[TriggerHit] = []
    news_scanned = 0
    news_l1_passed = 0
    news_l2_relevant = 0
    news_l2_mode: str | None = None
    news_l2_cost_usd = 0.0
    news_l2_cache_hits = 0
    news_l2_cache_misses = 0
    did_l2 = False
    mb = monitor_budget or build_monitor_budget(
        account=book.account,
        path=Path(budget_path) if budget_path else None,
    )
    tok = budget if budget is not None else token_budget_for_monitor(mb)
    cache = analysis_cache
    if cache is None and run_l2:
        cache = build_analysis_cache(
            account=book.account,
            path=Path(cache_path) if cache_path else None,
        )

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

    if run_news:
        if news_items is not None:
            feed = news_items
        elif demo:
            feed = _demo_news(book)
            notes.append("demo news")
        else:
            feed = fetch_monitor_news(
                lookback_hours=news_lookback_hours, now=when, include_live_flash=True
            )
            notes.append(f"news fetched={len(feed)}")
        names = _name_map(book)
        news_hits, news_stats = evaluate_news_triggers(
            feed,
            set(book.symbols()),
            name_by_symbol=names,
            industry_by_symbol=_industry_map(book),
        )
        news_scanned = news_stats.scanned
        news_l1_passed = news_stats.passed
        notes.append(
            f"news L1 scanned={news_stats.scanned} passed={news_stats.passed} "
            f"pass_rate={news_stats.pass_rate:.1%} "
            f"drop_rel={news_stats.drop_no_relevance} drop_sev={news_stats.drop_low_severity}"
        )
        if run_l2 and news_hits:
            if not mb.allow_l2():
                news_l2_mode = "l1_passthrough"
                news_l2_relevant = len(news_hits)
                reason = mb.degradation_reason() or "budget l1_only"
                notes.append(f"news L2 skipped: {reason}")
                logger.info("L2 skipped (monitor budget): %s", reason)
            else:
                did_l2 = True
                news_hits, l2_stats = await refine_news_hits_with_l2(
                    news_hits,
                    name_by_symbol=names,
                    llm=llm,
                    budget=tok,
                    enabled=True,
                    cache=cache,
                )
                news_l2_relevant = l2_stats.relevant
                news_l2_mode = l2_stats.mode
                news_l2_cost_usd = l2_stats.cost_usd
                news_l2_cache_hits = l2_stats.cache_hits
                news_l2_cache_misses = l2_stats.cache_misses
                if l2_stats.cost_usd > 0 or l2_stats.mode == "llm":
                    mb.record_spend(
                        l2_stats.cost_usd,
                        layer="l2",
                        calls=max(1, l2_stats.batches),
                    )
                notes.append(
                    f"news L2 mode={l2_stats.mode} relevant={l2_stats.relevant} "
                    f"dropped={l2_stats.dropped} deep={l2_stats.deep} "
                    f"cache_hit={l2_stats.cache_hits}/"
                    f"{l2_stats.cache_hits + l2_stats.cache_misses} "
                    f"cost_usd={l2_stats.cost_usd:.4f}"
                    + (f" note={l2_stats.note}" if l2_stats.note else "")
                )

    raw = [*price_hits, *risk_hits, *ann_hits, *news_hits]
    mb_stats = mb.stats()
    notes.append(mb.telemetry_line())

    state_path = Path(suppression_path) if suppression_path else default_state_path(book.account)
    state = SuppressionState.load(state_path)
    pol = policy or load_suppression_policy()
    decision = filter_hits(raw, state, pol, now=when)

    deliveries: list[DeliveryResult] = []
    if notify and decision.allowed:
        channel = notifier or build_notifier()
        # PushPlus free tier: ≤5 req/min — batch one cycle into a single digest.
        from quantagent.notify.pushplus import PushPlusNotifier

        if isinstance(channel, PushPlusNotifier):
            alerts = [format_alert(hit, when=when) for hit in decision.allowed]
            result = await channel.send_digest(alerts)
            deliveries.append(result)
            if result.ok:
                for hit in decision.allowed:
                    state.record(hit, when=when)
        else:
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
        ran_news=run_news,
        ran_l2=did_l2,
        news_scanned=news_scanned,
        news_l1_passed=news_l1_passed,
        news_l2_relevant=news_l2_relevant,
        news_l2_mode=news_l2_mode,
        news_l2_cost_usd=news_l2_cost_usd,
        news_l2_cache_hits=news_l2_cache_hits,
        news_l2_cache_misses=news_l2_cache_misses,
        budget_spent_usd=mb_stats.spent_usd,
        budget_remaining_usd=mb_stats.remaining_usd,
        budget_l1_only=mb_stats.l1_only,
        budget_l3_remaining=mb_stats.l3_remaining,
        budget_note=mb_stats.note,
    )


async def run_monitor_loop(
    *,
    positions_path: Path | str,
    market: str = "CN",
    demo: bool = False,
    notify: bool = True,
    notifier: NotifierAdapter | None = None,
    suppression_path: Path | str | None = None,
    cache_path: Path | str | None = None,
    budget_path: Path | str | None = None,
    max_cycles: int | None = None,
    interval_seconds: float | None = None,
    respect_sessions: bool = True,
    on_cycle: object | None = None,
) -> MonitorLoopResult:
    """Resident loop — price/risk (session-gated) + announcements + news L1/L2."""
    sched = load_monitor_schedule()
    sleep_s = float(
        interval_seconds if interval_seconds is not None else sched.price_snapshot.interval_seconds
    )
    lookback = int(sched.announcements.lookback_hours)
    news_lookback = int(sched.news.lookback_hours)
    cycles = 0
    last_result: MonitorOnceResult | None = None
    reason = "completed"
    book = load_position_book(Path(positions_path))
    shared_cache = build_analysis_cache(
        account=book.account,
        path=Path(cache_path) if cache_path else None,
    )
    shared_budget = build_monitor_budget(
        account=book.account,
        path=Path(budget_path) if budget_path else None,
    )

    try:
        while max_cycles is None or cycles < max_cycles:
            when = datetime.now(UTC)
            in_sess = in_cash_session(when, schedule=sched, market=market)

            if respect_sessions:
                run_price = in_sess or not sched.price_snapshot.sessions_only
                run_risk = in_sess or not sched.risk_check.sessions_only
                run_ann = in_sess or not sched.announcements.sessions_only
                run_news = in_sess or not sched.news.sessions_only
            else:
                run_price = True
                run_risk = True
                run_ann = True
                run_news = True

            if run_price or run_risk or run_ann or run_news:
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
                    run_news=run_news,
                    lookback_hours=lookback,
                    news_lookback_hours=news_lookback,
                    analysis_cache=shared_cache,
                    monitor_budget=shared_budget,
                    budget=token_budget_for_monitor(shared_budget),
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
