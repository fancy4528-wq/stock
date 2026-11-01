"""Shadow NAV, drawdown, and unfilled counts for one calendar month."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from quantagent.evaluation.review.types import ShadowMonthRow
from quantagent.evaluation.shadow.types import ShadowDayRecord, ShadowPortfolioId

PORTFOLIOS: tuple[ShadowPortfolioId, ...] = (
    "shadow_baseline",
    "shadow_factor",
    "shadow_quant",
    "shadow_agent",
    "shadow_fused",
    "shadow_fused_norisk",
)


def _compound(returns: list[float]) -> float:
    nav = 1.0
    for ret in returns:
        nav *= 1.0 + ret
    return nav - 1.0


def _month_drawdown(navs: list[float]) -> float | None:
    if not navs:
        return None
    peak = navs[0]
    drawdown = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        if peak > 0:
            drawdown = min(drawdown, nav / peak - 1.0)
    return drawdown


def load_shadow_month(
    shadow_dir: Path | str,
    *,
    start: date,
    end: date,
) -> tuple[list[ShadowMonthRow], list[str], set[str]]:
    """Month stats per portfolio. Last row for a date wins.

    The third value is the set of portfolios that have any readable row,
    including dates outside the month.
    """
    root = Path(shadow_dir)
    rows: list[ShadowMonthRow] = []
    warnings: list[str] = []
    ever_seen: set[str] = set()
    if not root.is_dir():
        return rows, [f"shadow 目录不存在：{root}"], ever_seen

    for portfolio in PORTFOLIOS:
        path = root / f"{portfolio}.jsonl"
        if not path.is_file():
            rows.append(ShadowMonthRow(portfolio=portfolio, n_days=0))
            continue
        by_day: dict[date, ShadowDayRecord] = {}
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = ShadowDayRecord.model_validate(json.loads(stripped))
            except (json.JSONDecodeError, ValidationError) as exc:
                warnings.append(f"{path.name} 第 {lineno} 行无法读取（{type(exc).__name__}）")
                continue
            if record.portfolio != portfolio:
                warnings.append(f"{path.name} 第 {lineno} 行组合是 {record.portfolio}，已跳过")
                continue
            by_day[record.as_of] = record
            ever_seen.add(portfolio)
        month = [by_day[day] for day in sorted(by_day) if start <= day <= end]
        if not month:
            rows.append(ShadowMonthRow(portfolio=portfolio, n_days=0))
            continue
        navs = [record.nav for record in month]
        rows.append(
            ShadowMonthRow(
                portfolio=portfolio,
                n_days=len(month),
                start=month[0].as_of,
                end=month[-1].as_of,
                ret_month=_compound([record.ret_1d for record in month]),
                ret_cum=month[-1].ret_cum,
                max_drawdown=_month_drawdown(navs),
                nav=month[-1].nav,
                n_unfilled=sum(len(record.unfilled) for record in month),
            )
        )
    return rows, warnings, ever_seen
