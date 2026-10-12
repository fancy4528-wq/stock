"""Forward-return labels for factor evaluation.

Labels are pure transforms on price panels. Callers must ensure prices are
Point-in-Time safe; this module never queries the database.

Gate 3 / docs/07-quant-engine.md §4.3: samples that cannot be entered
(limit-up or suspended on the entry bar) get NaN labels and drop out of IC.
"""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import entity_col, require_columns, sorted_prices
from quantagent.shared.errors import QuantAgentError

# Decision at close of T → earliest executable entry is T+1 (open).
DEFAULT_ENTRY_OFFSET: int = 1
LIMIT_UP_COL: str = "is_limit_up"
SUSPENDED_COL: str = "is_suspended"


class LabelError(QuantAgentError):
    """Invalid label construction input."""


def forward_return_col(horizon: int) -> str:
    if horizon < 1:
        raise LabelError(f"horizon must be >= 1, got {horizon}")
    return f"fwd_ret_{horizon}d"


def has_tradeability_flags(panel: pl.DataFrame) -> bool:
    """True when both limit-up and suspended columns are present."""
    return LIMIT_UP_COL in panel.columns and SUSPENDED_COL in panel.columns


def entry_untradeable_mask(
    panel: pl.DataFrame,
    *,
    entry_offset: int = DEFAULT_ENTRY_OFFSET,
    date_col: str = "trade_date",
) -> pl.Series:
    """Boolean mask: True when the entry bar (``t + entry_offset``) is untradeable.

    Untradeable = ``is_limit_up`` or ``is_suspended`` on the entry bar.
    Missing future flags (panel end) are treated as tradeable (False) so we do
    not blank labels that are already null from missing future prices.
    """
    if entry_offset < 0:
        raise LabelError(f"entry_offset must be >= 0, got {entry_offset}")
    if not has_tradeability_flags(panel):
        raise LabelError(
            f"panel missing {LIMIT_UP_COL!r} and/or {SUSPENDED_COL!r} "
            "for tradeability mask"
        )

    prices = sorted_prices(panel)
    ent = entity_col(prices)
    require_columns(prices, [date_col, LIMIT_UP_COL, SUSPENDED_COL], context="entry_mask")

    if entry_offset == 0:
        up = pl.col(LIMIT_UP_COL).fill_null(False)
        sus = pl.col(SUSPENDED_COL).fill_null(False)
    else:
        up = pl.col(LIMIT_UP_COL).shift(-entry_offset).over(ent).fill_null(False)
        sus = pl.col(SUSPENDED_COL).shift(-entry_offset).over(ent).fill_null(False)

    return prices.select((up | sus).alias("untradeable")).to_series()


def mask_untradeable_labels(
    panel: pl.DataFrame,
    label_cols: list[str] | tuple[str, ...],
    *,
    entry_offset: int = DEFAULT_ENTRY_OFFSET,
    date_col: str = "trade_date",
) -> pl.DataFrame:
    """Set listed label columns to null where the entry bar is untradeable."""
    cols = [c for c in label_cols if c in panel.columns]
    if not cols:
        return panel
    if not has_tradeability_flags(panel):
        return panel

    mask = entry_untradeable_mask(panel, entry_offset=entry_offset, date_col=date_col)
    out = panel.with_columns(mask.alias("_untradeable_entry"))
    exprs = [
        pl.when(pl.col("_untradeable_entry"))
        .then(None)
        .otherwise(pl.col(c))
        .alias(c)
        for c in cols
    ]
    return out.with_columns(exprs).drop("_untradeable_entry")


def attach_forward_returns(
    prices: pl.DataFrame,
    *,
    horizons: list[int] | tuple[int, ...] = (1, 5, 20),
    price_col: str = "close",
    exclude_untradeable: bool = True,
    entry_offset: int = DEFAULT_ENTRY_OFFSET,
) -> pl.DataFrame:
    """Append ``fwd_ret_{h}d`` = close_{t+h} / close_t - 1 for each horizon.

    Value at row ``t`` uses future prices and is therefore a *label*, not a
    feature. Evaluation must align factor at ``t`` with this label at ``t``.

    When ``exclude_untradeable`` is True and tradeability flags exist, labels
    are set to null if the entry bar (``t + entry_offset``, default T+1) is
    limit-up or suspended — matching docs/07-quant-engine.md §4.3. Synthetic
    panels without those columns are left unchanged.
    """
    if not horizons:
        raise LabelError("horizons must be non-empty")
    prices = sorted_prices(prices)
    ent = entity_col(prices)
    require_columns(prices, [price_col], context="attach_forward_returns")

    out = prices
    label_cols: list[str] = []
    for h in horizons:
        if h < 1:
            raise LabelError(f"horizon must be >= 1, got {h}")
        col = forward_return_col(h)
        label_cols.append(col)
        out = out.with_columns(
            (pl.col(price_col).shift(-h).over(ent) / pl.col(price_col) - 1.0).alias(col)
        )

    if exclude_untradeable and has_tradeability_flags(out):
        out = mask_untradeable_labels(
            out,
            label_cols,
            entry_offset=entry_offset,
        )
    return out


def tradeability_label_stats(
    panel: pl.DataFrame,
    *,
    entry_offset: int = DEFAULT_ENTRY_OFFSET,
    date_col: str = "trade_date",
) -> dict[str, int]:
    """Counts for report notes: how many rows would be masked at entry."""
    if not has_tradeability_flags(panel):
        return {"n_rows": panel.height, "n_untradeable_entry": 0, "flags_present": 0}
    mask = entry_untradeable_mask(panel, entry_offset=entry_offset, date_col=date_col)
    return {
        "n_rows": panel.height,
        "n_untradeable_entry": int(mask.sum()),
        "flags_present": 1,
    }
