"""Build a feature-store panel from an already point-in-time FactorInput."""

from __future__ import annotations

import polars as pl

from quantagent.quant.features.base import FactorInput
from quantagent.quant.features.compute import compute_factors
from quantagent.quant.features.registry import ALL_FACTOR_CODES, get_factor
from quantagent.quant.store.feature_store import (
    FeatureStore,
    FeatureStoreError,
    bundle_code_version,
)


def factor_versions(codes: list[str] | tuple[str, ...]) -> dict[str, str]:
    return {code: get_factor(code).version for code in codes}


def build_store_panel(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
    *,
    as_of_only: bool = False,
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Compute factor columns visible at ``data.as_of``.

    Prices after ``as_of`` are dropped before compute. ``as_of_only`` keeps the
    decision date, which is the row an incremental update writes.
    """
    if "security_id" not in data.prices.columns or "trade_date" not in data.prices.columns:
        raise FeatureStoreError("store panel requires security_id and trade_date")
    selected = list(codes) if codes is not None else list(ALL_FACTOR_CODES)
    if not selected:
        raise FeatureStoreError("at least one factor code is required")
    versions = factor_versions(selected)
    prices = data.prices.filter(pl.col("trade_date") <= data.as_of)
    bound = FactorInput(
        prices=prices,
        financials=data.financials,
        valuations=data.valuations,
        money_flow=data.money_flow,
        events=data.events,
        industry=data.industry,
        as_of=data.as_of,
        meta=data.meta,
    )
    frame = compute_factors(bound, selected)
    if as_of_only:
        frame = frame.filter(pl.col("trade_date") == data.as_of)
    code_version = bundle_code_version(versions)
    factors = sorted(versions)
    frame = frame.select(["security_id", "trade_date", *factors]).with_columns(
        pl.lit(code_version).alias("code_version")
    )
    return frame, versions


def append_factors(
    store: FeatureStore,
    data: FactorInput,
    *,
    market: str,
    codes: list[str] | tuple[str, ...] | None = None,
) -> int:
    """Compute factors on the supplied lookback and store only ``as_of``."""
    frame, versions = build_store_panel(data, codes, as_of_only=True)
    if frame.is_empty():
        raise FeatureStoreError(f"no rows on as_of={data.as_of.isoformat()}")
    store.append(market, frame, versions=versions)
    return frame.height


def rebuild_factors(
    store: FeatureStore,
    data: FactorInput,
    *,
    market: str,
    codes: list[str] | tuple[str, ...] | None = None,
) -> int:
    """Replace the market panel with every date up to ``as_of``."""
    frame, versions = build_store_panel(data, codes, as_of_only=False)
    if frame.is_empty():
        raise FeatureStoreError(f"no rows on or before as_of={data.as_of.isoformat()}")
    store.rebuild(market, frame, versions=versions)
    return frame.height
