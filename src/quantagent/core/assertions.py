"""Runtime assertions for data correctness."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import polars as pl

from quantagent.shared.errors import LookaheadError


def _normalize_as_of(as_of: date | datetime, sample: Any) -> date | datetime:
    """Align ``as_of`` type/timezone with ``sample`` for comparison."""
    if isinstance(as_of, datetime):
        return as_of
    # as_of is date
    if isinstance(sample, datetime):
        if sample.tzinfo is not None:
            return datetime.combine(as_of, time(23, 59, 59), tzinfo=sample.tzinfo)
        return datetime.combine(as_of, time(23, 59, 59))
    return as_of


def assert_no_lookahead(
    df: pl.DataFrame,
    as_of: date | datetime,
    time_col: str,
) -> None:
    """Ensure every row's timestamp is <= ``as_of``."""
    if df.is_empty() or time_col not in df.columns:
        return
    max_ts: Any = df[time_col].max()
    if max_ts is None:
        return
    as_of_cmp = _normalize_as_of(as_of, max_ts)
    if max_ts > as_of_cmp:
        raise LookaheadError(f"Data contains {time_col}={max_ts} > as_of={as_of}")
