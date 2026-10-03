"""Historical L1→L2→L3 funnel replay (Gate 2b benchmark).

One cycle per CN session at 18:00 Asia/Shanghai, 24h flash lookback.
Does not notify, does not persist production cache/budget/suppression.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from quantagent.agents.llm.client import LLMClient, NullLLMClient
from quantagent.core.calendar import TradingCalendar
from quantagent.monitor.announcements_fetch import fetch_holding_announcements
from quantagent.monitor.budget import MonitorBudget, load_monitor_budget_config
from quantagent.monitor.cache import AnalysisCache
from quantagent.monitor.engine import run_monitor_once, token_budget_for_monitor
from quantagent.monitor.news_fetch import fetch_news_from_db
from quantagent.monitor.suppression import SuppressionPolicy
from quantagent.monitor.triggers.announcement import AnnouncementItem
from quantagent.monitor.triggers.news import NewsFeedItem
from quantagent.notify.base import LogNotifier
from quantagent.positions.manual import load_position_book

SHANGHAI = ZoneInfo("Asia/Shanghai")
GATE_L1_PASS = 0.05
GATE_L2_TO_L3 = 0.25
GATE_L3_PER_DAY = 10
GATE_USD_PER_DAY = 0.30
GATE_CACHE_HIT = 0.15


@dataclass
class FunnelDayRow:
    as_of: date
    scanned: int = 0
    l1_passed: int = 0
    l2_relevant: int = 0
    l2_dropped: int = 0
    l2_deep: int = 0
    l3_analyzed: int = 0
    l3_skipped_cap: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    l2_cost_usd: float = 0.0
    l3_cost_usd: float = 0.0
    l2_mode: str | None = None
    l3_mode: str | None = None
    ann_hits: int = 0

    @property
    def l1_pass_rate(self) -> float | None:
        if self.scanned <= 0:
            return None
        return self.l1_passed / self.scanned

    @property
    def l2_to_l3_rate(self) -> float | None:
        if self.l2_relevant <= 0:
            return None
        return self.l2_deep / self.l2_relevant

    @property
    def cache_hit_rate(self) -> float | None:
        total = self.cache_hits + self.cache_misses
        if total <= 0:
            return None
        return self.cache_hits / total

    @property
    def cost_usd(self) -> float:
        return float(self.l2_cost_usd) + float(self.l3_cost_usd)


@dataclass
class FunnelReplaySummary:
    start: date
    end: date
    positions_path: str
    holdings: list[str]
    mode: str
    days: list[FunnelDayRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def sessions(self) -> int:
        return len(self.days)

    @property
    def scanned(self) -> int:
        return sum(d.scanned for d in self.days)

    @property
    def l1_passed(self) -> int:
        return sum(d.l1_passed for d in self.days)

    @property
    def l1_pass_rate(self) -> float | None:
        if self.scanned <= 0:
            return None
        return self.l1_passed / self.scanned

    @property
    def l2_relevant(self) -> int:
        return sum(d.l2_relevant for d in self.days)

    @property
    def l2_deep(self) -> int:
        return sum(d.l2_deep for d in self.days)

    @property
    def l2_to_l3_rate(self) -> float | None:
        if self.l2_relevant <= 0:
            return None
        return self.l2_deep / self.l2_relevant

    @property
    def l3_analyzed(self) -> int:
        return sum(d.l3_analyzed for d in self.days)

    @property
    def l3_max_day(self) -> int:
        if not self.days:
            return 0
        return max(d.l3_analyzed for d in self.days)

    @property
    def cache_hits(self) -> int:
        return sum(d.cache_hits for d in self.days)

    @property
    def cache_misses(self) -> int:
        return sum(d.cache_misses for d in self.days)

    @property
    def cache_hit_rate(self) -> float | None:
        total = self.cache_hits + self.cache_misses
        if total <= 0:
            return None
        return self.cache_hits / total

    @property
    def cost_usd(self) -> float:
        return sum(d.cost_usd for d in self.days)

    @property
    def usd_per_day(self) -> float:
        if self.sessions <= 0:
            return 0.0
        return self.cost_usd / self.sessions

    def gate_rows(self) -> list[tuple[str, str, str, str]]:
        return [
            (
                "L1 pass rate",
                _pct(self.l1_pass_rate),
                "< 5%",
                _gate_lt(self.l1_pass_rate, GATE_L1_PASS),
            ),
            (
                "L2 → L3 rate",
                _pct(self.l2_to_l3_rate),
                "< 25%",
                _gate_lt(self.l2_to_l3_rate, GATE_L2_TO_L3),
            ),
            (
                "L3 max / day",
                str(self.l3_max_day),
                f"≤ {GATE_L3_PER_DAY}",
                "PASS" if self.l3_max_day <= GATE_L3_PER_DAY else "FAIL",
            ),
            (
                "Monitor USD / day",
                f"${self.usd_per_day:.4f}",
                f"< ${GATE_USD_PER_DAY:.2f}",
                "PASS" if self.usd_per_day < GATE_USD_PER_DAY else "FAIL",
            ),
            (
                "L2 cache hit rate",
                (
                    _pct(self.cache_hit_rate)
                    if self.mode != "heuristic"
                    else "n/a (heuristic L2 not cached)"
                ),
                "> 15%",
                (
                    _gate_gt(self.cache_hit_rate, GATE_CACHE_HIT)
                    if self.mode != "heuristic"
                    else "n/a"
                ),
            ),
        ]


def session_cutoff(as_of: date) -> datetime:
    return datetime.combine(as_of, time(18, 0), tzinfo=SHANGHAI)


def replay_sessions(
    start: date,
    end: date,
    *,
    market: str = "CN",
    open_dates: Sequence[date] | None = None,
) -> list[date]:
    if open_dates is not None:
        return [d for d in sorted(set(open_dates)) if start <= d <= end]
    try:
        cal = TradingCalendar(market)
        if not cal.is_empty():
            return cal.trading_days(start, end)
    except Exception:  # noqa: BLE001 — tests / missing DB fall back to weekdays
        pass
    days: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    return days


async def replay_funnel(
    *,
    positions_path: Path | str,
    start: date,
    end: date,
    market: str = "CN",
    llm: LLMClient | None = None,
    news_by_day: Mapping[date, Sequence[NewsFeedItem]] | None = None,
    announcements_by_day: Mapping[date, Sequence[AnnouncementItem]] | None = None,
    run_announcements: bool = True,
    news_lookback_hours: int = 24,
    announcement_lookback_hours: int = 72,
    news_limit: int = 800,
    work_dir: Path | str | None = None,
    sessions: Sequence[date] | None = None,
) -> FunnelReplaySummary:
    path = Path(positions_path)
    book = load_position_book(path)
    holdings = list(book.symbols())
    client = llm if llm is not None else NullLLMClient()
    mode = "heuristic" if isinstance(client, NullLLMClient) else "llm"
    cache = AnalysisCache(path=None)
    cfg = load_monitor_budget_config()
    days = replay_sessions(start, end, market=market, open_dates=sessions)
    tmp_owner: TemporaryDirectory[str] | None = None
    if work_dir is not None:
        scratch = Path(work_dir)
        scratch.mkdir(parents=True, exist_ok=True)
    else:
        tmp_owner = TemporaryDirectory(prefix="funnel-replay-")
        scratch = Path(tmp_owner.name)
    summary = FunnelReplaySummary(
        start=start,
        end=end,
        positions_path=str(path),
        holdings=holdings,
        mode=mode,
    )
    if news_by_day is None:
        summary.notes.append(
            "D-class corpus = news.source in (cls, em); "
            "em_announce is C-class and excluded from L1."
        )
        summary.notes.append(
            "Fetch window is PIT-closed: published_at in (cutoff-lookback, cutoff]; "
            "cls/em flash ingest in this DB starts 2026-09-12."
        )
    summary.notes.append(
        "One cycle per session (not 3-minute polling). "
        "Heuristic L2 does not write the analysis cache (LLM-only)."
    )
    summary.notes.append(
        "L1 requires entity match AND keyword severity >= medium; "
        "holding-name mentions without keywords do not pass."
    )

    try:
        for as_of in days:
            when = session_cutoff(as_of)
            if news_by_day is not None:
                feed = list(news_by_day.get(as_of, []))
            else:
                feed = fetch_news_from_db(
                    lookback_hours=news_lookback_hours,
                    limit=news_limit,
                    now=when,
                )
            if not run_announcements:
                ann_items: list[AnnouncementItem] = []
            elif announcements_by_day is not None:
                ann_items = list(announcements_by_day.get(as_of, []))
            else:
                ann_items = fetch_holding_announcements(
                    holdings,
                    lookback_hours=announcement_lookback_hours,
                    now=when,
                )
            mb = MonitorBudget(config=cfg, day=as_of, path=None)
            tok = token_budget_for_monitor(mb)
            result = await run_monitor_once(
                positions_path=path,
                market=market,
                demo=False,
                notify=False,
                notifier=LogNotifier(),
                suppression_path=scratch / f"sup_{as_of.isoformat()}.json",
                policy=SuppressionPolicy(quiet_hours=[]),
                persist_peak_nav=False,
                now=when,
                run_price=False,
                run_risk=False,
                run_announcements=run_announcements,
                run_news=True,
                run_l2=True,
                run_l3=True,
                announcement_items=ann_items,
                news_items=feed,
                llm=client,
                budget=tok,
                monitor_budget=mb,
                analysis_cache=cache,
            )
            summary.days.append(
                FunnelDayRow(
                    as_of=as_of,
                    scanned=result.news_scanned,
                    l1_passed=result.news_l1_passed,
                    l2_relevant=result.news_l2_relevant,
                    l2_dropped=result.news_l2_dropped,
                    l2_deep=result.news_l2_deep,
                    l3_analyzed=result.news_l3_analyzed,
                    l3_skipped_cap=result.news_l3_skipped_cap,
                    cache_hits=result.news_l2_cache_hits,
                    cache_misses=result.news_l2_cache_misses,
                    l2_cost_usd=result.news_l2_cost_usd,
                    l3_cost_usd=result.news_l3_cost_usd,
                    l2_mode=result.news_l2_mode,
                    l3_mode=result.news_l3_mode,
                    ann_hits=sum(1 for h in result.hits_raw if h.code.startswith("ANN_")),
                )
            )
        flash_days = sum(1 for d in summary.days if d.scanned > 0)
        summary.notes.append(
            f"Sessions={summary.sessions}; days with D-class flash={flash_days}."
        )
        return summary
    finally:
        if tmp_owner is not None:
            tmp_owner.cleanup()


def format_cost_log_section(summary: FunnelReplaySummary, *, generated_on: date) -> str:
    gates = "\n".join(
        f"| {name} | {actual} | {threshold} | {verdict} |"
        for name, actual, threshold, verdict in summary.gate_rows()
    )
    day_lines = [
        "| as_of | scanned | L1 pass | L1 rate | L2 rel | L2 drop | L2 deep "
        "| L3 | ANN hits | cache hit/miss | USD | L2 mode | L3 mode |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---|",
    ]
    for d in summary.days:
        day_lines.append(
            f"| {d.as_of.isoformat()} | {d.scanned} | {d.l1_passed} | {_pct(d.l1_pass_rate)} | "
            f"{d.l2_relevant} | {d.l2_dropped} | {d.l2_deep} | {d.l3_analyzed} | "
            f"{d.ann_hits} | {d.cache_hits}/{d.cache_misses} | "
            f"${d.cost_usd:.4f} | {d.l2_mode or '-'} | {d.l3_mode or '-'} |"
        )
    notes = "\n".join(f"- {n}" for n in summary.notes)
    holdings = ", ".join(summary.holdings) if summary.holdings else "(empty)"
    return (
        f"\n## Gate 2b funnel replay ({generated_on.isoformat()})\n\n"
        f"Window: {summary.start.isoformat()} ... {summary.end.isoformat()} "
        f"({summary.sessions} CN sessions). "
        f"Holdings: `{holdings}`. Mode: **{summary.mode}**. "
        f"Cutoff 18:00 Asia/Shanghai, flash lookback 24h.\n\n"
        f"| Gate 2b | Actual | Threshold | Result |\n"
        f"|---|---|---|---|\n"
        f"{gates}\n\n"
        f"Totals: scanned={summary.scanned} L1_pass={summary.l1_passed} "
        f"L2_rel={summary.l2_relevant} L2_deep={summary.l2_deep} "
        f"L3={summary.l3_analyzed} USD=${summary.cost_usd:.4f} "
        f"(${summary.usd_per_day:.4f}/day).\n\n"
        f"{chr(10).join(day_lines)}\n\n"
        f"{notes}\n"
    )


def append_cost_log(path: Path, section: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Gate 2b funnel replay"
    idx = existing.find(marker)
    if idx >= 0:
        existing = existing[:idx].rstrip() + "\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + section, encoding="utf-8")


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _gate_lt(value: float | None, limit: float) -> str:
    if value is None:
        return "n/a"
    return "PASS" if value < limit else "FAIL"


def _gate_gt(value: float | None, limit: float) -> str:
    if value is None:
        return "n/a"
    return "PASS" if value > limit else "FAIL"


__all__ = [
    "FunnelDayRow",
    "FunnelReplaySummary",
    "append_cost_log",
    "format_cost_log_section",
    "replay_funnel",
    "replay_sessions",
    "session_cutoff",
]
