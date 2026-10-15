"""Walk-forward date splits with embargo (docs/07-quant-engine.md §6.1)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping the day to the target month length."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


class WalkForwardConfig(BaseModel):
    """Rolling train / val / test windows with an embargo gap."""

    train_months: int = 36
    val_months: int = 6
    test_months: int = 6
    step_months: int = 6
    embargo_days: int = 10
    holdout_start: date | None = None

    def model_post_init(self, __context: object) -> None:
        for name in (
            "train_months",
            "val_months",
            "test_months",
            "step_months",
            "embargo_days",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be >= 1")


@dataclass(frozen=True)
class WalkForwardFold:
    """One walk-forward fold (inclusive date bounds)."""

    fold_id: int
    train_start: date
    train_end: date
    val_start: date
    val_end: date
    test_start: date
    test_end: date


def generate_folds(
    panel_start: date,
    panel_end: date,
    config: WalkForwardConfig | None = None,
) -> list[WalkForwardFold]:
    """Generate expanding-start rolling folds that fit inside ``[panel_start, panel_end]``.

    Layout per fold (embargo after train and after val)::

        [===== train =====]|emb|[== val ==]|emb|[== test ==]
    """
    cfg = config or WalkForwardConfig()
    end_cap = panel_end
    if cfg.holdout_start is not None:
        end_cap = min(end_cap, cfg.holdout_start - timedelta(days=1))

    folds: list[WalkForwardFold] = []
    fold_id = 0
    cursor = panel_start
    embargo = timedelta(days=cfg.embargo_days)

    while True:
        train_start = cursor
        train_end = add_months(train_start, cfg.train_months) - timedelta(days=1)
        val_start = train_end + embargo + timedelta(days=1)
        val_end = add_months(val_start, cfg.val_months) - timedelta(days=1)
        test_start = val_end + embargo + timedelta(days=1)
        test_end = add_months(test_start, cfg.test_months) - timedelta(days=1)

        if train_end < train_start or val_end < val_start or test_end < test_start:
            break
        if test_end > end_cap:
            # Shrink final test window if a partial fold still has ≥1 month.
            if test_start <= end_cap and (end_cap - test_start).days >= 20:
                test_end = end_cap
            else:
                break

        folds.append(
            WalkForwardFold(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                val_start=val_start,
                val_end=val_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        fold_id += 1
        cursor = add_months(cursor, cfg.step_months)
        if cursor >= end_cap:
            break

    return folds
