"""IC decay across prediction horizons."""

from __future__ import annotations

import polars as pl

from quantagent.quant.evaluation.ic import EvaluationError, daily_ic_series, summarize_ic
from quantagent.quant.labels.targets import attach_forward_returns, forward_return_col


def ic_decay(
    panel: pl.DataFrame,
    *,
    factor_col: str,
    price_col: str = "close",
    horizons: list[int] | tuple[int, ...] = (1, 5, 10, 20),
    date_col: str = "trade_date",
    min_names: int = 3,
) -> tuple[list[int], list[float]]:
    """Mean Spearman IC of ``factor_col`` vs forward returns at each horizon.

    ``panel`` must contain entity id, ``trade_date``, ``close`` (or ``price_col``),
    and ``factor_col``. Horizons without enough observations yield 0.0.
    """
    needed = {date_col, price_col, factor_col}
    missing = sorted(needed - set(panel.columns))
    if missing:
        raise EvaluationError(f"ic_decay panel missing columns: {missing}")

    # Reuse existing fwd_ret_* columns when present to avoid recomputation.
    missing_h = [h for h in horizons if forward_return_col(h) not in panel.columns]
    labeled = (
        attach_forward_returns(panel, horizons=missing_h, price_col=price_col)
        if missing_h
        else panel
    )

    hs: list[int] = []
    means: list[float] = []
    for h in horizons:
        ret_col = forward_return_col(h)
        ics = daily_ic_series(
            labeled,
            factor_col=factor_col,
            return_col=ret_col,
            date_col=date_col,
            min_names=min_names,
        )
        summary = summarize_ic(
            ics["ic"] if not ics.is_empty() else pl.Series("ic", [], dtype=pl.Float64)
        )
        hs.append(h)
        means.append(summary.ic_mean)
    return hs, means
