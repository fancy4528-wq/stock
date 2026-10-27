"""Build real CSI300 L2 Top-N bars + scores for Gate 4 portfolio backtest."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import polars as pl

from quantagent.backtest.engine import _price_bar_from_row
from quantagent.evaluation.shadow.quant_signals import (
    CSI300_L2_IC_MEANS_5Y,
    DEFAULT_QUANT_LOOKBACK_DAYS,
)
from quantagent.execution.broker.simulated import PriceBar
from quantagent.quant.evaluation.panel_loader import codes_for_real_l1, load_l1_factor_input
from quantagent.quant.features.base import entity_col
from quantagent.quant.features.transform import DEFAULT_TRANSFORM, TransformConfig
from quantagent.quant.models.baseline import (
    CSI300_L1_ADMITTED_5Y,
    COMBO_EQUAL,
    build_l2_panel,
    combine_equal_weight,
)
from quantagent.shared.errors import QuantAgentError

if TYPE_CHECKING:
    from quantagent.core.repository.pit import PITRepository

# Align with Makefile START / CSI300 5y L1–L2 window (holdout starts 2026-10-14).
CSI300_L2_BACKTEST_START: date = date(2021, 10, 14)
CSI300_L2_BACKTEST_END: date = date(2026, 10, 13)


@dataclass(frozen=True)
class RealL2TopNPanel:
    """Bars + close-of-day L2 scores for :class:`L2TopNBacktest`."""

    bars: list[PriceBar]
    scores: dict[date, dict[str, float]]
    start: date
    end: date
    n_score_days: int
    n_symbols_scored: int
    membership_filtered: bool
    notes: tuple[str, ...] = ()
    membership: dict[date, frozenset[str]] | None = None
    # Rank/transformed component columns + ``l2_equal`` (for single-factor controls).
    factor_panel: pl.DataFrame | None = None
    factor_codes: tuple[str, ...] = ()
    ic_means: dict[str, float] | None = None


def membership_by_session(
    sessions: list[date],
    *,
    universe: str,
    repo: PITRepository,
) -> dict[date, frozenset[str]]:
    """Map each session to CSI300 (etc.) members via latest snapshot ≤ day."""
    snaps = repo.list_universe_snapshot_dates(name=universe)
    if not snaps:
        return {d: frozenset() for d in sessions}
    cache: dict[date, frozenset[str]] = {}
    for snap in snaps:
        cache[snap] = frozenset(repo.resolve_universe_symbols(as_of=snap, name=universe))
    out: dict[date, frozenset[str]] = {}
    for day in sessions:
        idx = bisect_right(snaps, day) - 1
        out[day] = cache[snaps[idx]] if idx >= 0 else frozenset()
    return out


def scores_from_l2_panel(
    panel: pl.DataFrame,
    *,
    start: date,
    end: date,
    membership: dict[date, frozenset[str]] | None = None,
) -> dict[date, dict[str, float]]:
    """Pivot ``l2_equal`` into ``date → symbol → score`` inside ``[start, end]``."""
    if COMBO_EQUAL not in panel.columns:
        raise QuantAgentError(f"panel missing {COMBO_EQUAL!r}")
    key = "symbol" if "symbol" in panel.columns else entity_col(panel)
    rows = panel.filter(
        (pl.col("trade_date") >= start)
        & (pl.col("trade_date") <= end)
        & pl.col(COMBO_EQUAL).is_not_null()
    ).select(["trade_date", key, COMBO_EQUAL])
    scores: dict[date, dict[str, float]] = {}
    for row in rows.iter_rows(named=True):
        day = row["trade_date"]
        if not isinstance(day, date):
            day = date.fromisoformat(str(day))
        sym = str(row[key])
        if membership is not None:
            members = membership.get(day)
            if members is not None and sym not in members:
                continue
        scores.setdefault(day, {})[sym] = float(row[COMBO_EQUAL])
    return scores


def bars_from_prices(
    prices: pl.DataFrame,
    *,
    start: date,
    end: date,
) -> list[PriceBar]:
    """Map PIT price rows in ``[start, end]`` to :class:`PriceBar`."""
    if "symbol" not in prices.columns or "trade_date" not in prices.columns:
        raise QuantAgentError("prices need symbol and trade_date")
    window = prices.filter(
        (pl.col("trade_date") >= start) & (pl.col("trade_date") <= end)
    )
    bars: list[PriceBar] = []
    for row in window.iter_rows(named=True):
        bars.append(_price_bar_from_row(str(row["symbol"]), row))
    return bars


def build_real_l2_topn_panel(
    *,
    universe: str = "csi300",
    start: date = CSI300_L2_BACKTEST_START,
    end: date = CSI300_L2_BACKTEST_END,
    lookback_days: int = DEFAULT_QUANT_LOOKBACK_DAYS,
    filter_membership: bool = True,
    repo: PITRepository | None = None,
    transform: TransformConfig | bool = DEFAULT_TRANSFORM,
    codes: list[str] | tuple[str, ...] | None = None,
    ic_means: dict[str, float] | None = None,
) -> RealL2TopNPanel:
    """Load PIT panels, freeze-sign L2 equal scores, and OHLCV bars.

    IC means default to :data:`CSI300_L2_IC_MEANS_5Y` (same as ``shadow_quant``).
    Scores after ``end`` are not produced; prices before ``start`` are warm-up only.
    """
    from quantagent.core.repository.pit import PITRepository

    if end < start:
        raise QuantAgentError("backtest end is before start")

    pit = repo or PITRepository()
    selected = list(codes) if codes is not None else list(CSI300_L1_ADMITTED_5Y)
    means = dict(ic_means) if ic_means is not None else dict(CSI300_L2_IC_MEANS_5Y)

    load_start = start - timedelta(days=lookback_days)
    print(
        f"l2-panel: load universe={universe} prices={load_start}..{end} "
        f"as_of={end} (trade window {start}..{end})",
        flush=True,
    )
    data = load_l1_factor_input(
        universe=universe,
        start=load_start,
        end=end,
        as_of=end,
        repo=pit,
    )
    runnable, skipped = codes_for_real_l1(data, selected)
    if skipped:
        print(f"l2-panel: skipped factors (no valuation): {skipped}", flush=True)
    if not runnable:
        raise QuantAgentError("no runnable L1 factors for L2 panel")

    print(f"l2-panel: build factors n={len(runnable)}", flush=True)
    panel = build_l2_panel(data, runnable, transform=transform)
    panel = combine_equal_weight(panel, runnable, means, out_col=COMBO_EQUAL)

    membership: dict[date, frozenset[str]] | None = None
    if filter_membership:
        sessions = sorted(
            {
                d
                for d in panel.filter(
                    (pl.col("trade_date") >= start) & (pl.col("trade_date") <= end)
                )["trade_date"].to_list()
            }
        )
        print(
            f"l2-panel: resolve {universe} membership for {len(sessions)} sessions",
            flush=True,
        )
        membership = membership_by_session(sessions, universe=universe, repo=pit)

    scores = scores_from_l2_panel(
        panel, start=start, end=end, membership=membership
    )
    bars = bars_from_prices(data.prices, start=start, end=end)
    scored_syms = {s for day in scores.values() for s in day}
    notes = (
        "frozen CSI300_L2_IC_MEANS_5Y (sign align only; same as shadow_quant)",
        (
            f"scores filtered to {universe} membership @ signal day"
            if filter_membership
            else f"scores on historical {universe} union (no daily membership filter)"
        ),
        f"lookback_days={lookback_days} for factor warm-up",
    )
    print(
        f"l2-panel: bars={len(bars)} score_days={len(scores)} "
        f"symbols_scored={len(scored_syms)}",
        flush=True,
    )
    return RealL2TopNPanel(
        bars=bars,
        scores=scores,
        start=start,
        end=end,
        n_score_days=len(scores),
        n_symbols_scored=len(scored_syms),
        membership_filtered=filter_membership,
        notes=notes,
        membership=membership,
        factor_panel=panel,
        factor_codes=tuple(runnable),
        ic_means=means,
    )
