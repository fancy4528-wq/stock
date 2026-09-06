"""Value factors — EP_TTM exercises financial PIT handling."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from quantagent.quant.features.base import (
    Factor,
    FactorError,
    FactorInput,
    entity_col,
    require_columns,
    sorted_prices,
)


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def filter_financials_as_of(financials: pl.DataFrame, as_of: date) -> pl.DataFrame:
    """Keep only statements announced on or before ``as_of`` (date precision)."""
    require_columns(financials, ["announced_at"], context="financials")
    if financials.is_empty():
        return financials
    announced = financials.get_column("announced_at").to_list()
    mask = []
    for raw in announced:
        d = _as_date(raw)
        mask.append(d is not None and d <= as_of)
    return financials.filter(pl.Series(mask))


def ttm_eps_from_financials(financials: pl.DataFrame, *, as_of: date) -> pl.DataFrame:
    """Build latest visible TTM EPS per entity at ``as_of``.

    Preference order per security:
    1. Sum of the four most recent quarterly ``eps`` rows (period_type Q1/Q3 or
       month-end 3/31, 6/30, 9/30, 12/31) when ≥4 quarters exist.
    2. Else the latest FY ``eps``.
    3. Else the latest single-period ``eps``.
    """
    visible = filter_financials_as_of(financials, as_of)
    if visible.is_empty():
        return pl.DataFrame(
            schema={
                "security_id": pl.Int64,
                "symbol": pl.Utf8,
                "eps_ttm": pl.Float64,
            }
        )

    has_entity = "security_id" in visible.columns or "symbol" in visible.columns
    ent = entity_col(visible) if has_entity else None
    if ent is None:
        raise FactorError("financials must contain security_id or symbol")
    require_columns(visible, ["eps", "period_end"], context="financials")

    quarter_ends = {(3, 31), (6, 30), (9, 30), (12, 31)}
    rows: list[dict[str, object]] = []
    for key, group in visible.sort(["period_end"]).group_by(ent, maintain_order=True):
        entity_key = key[0] if isinstance(key, tuple) else key
        eps_vals = group.get_column("eps").to_list()
        period_ends = group.get_column("period_end").to_list()
        period_types = (
            group.get_column("period_type").to_list()
            if "period_type" in group.columns
            else [None] * len(eps_vals)
        )

        quarterly: list[float] = []
        fy_eps: float | None = None
        latest_eps: float | None = None
        for eps, pend, ptype in zip(eps_vals, period_ends, period_types, strict=True):
            if eps is None:
                continue
            eps_f = float(eps)
            latest_eps = eps_f
            pdate = _as_date(pend)
            is_q = False
            if ptype in {"Q1", "Q2", "Q3", "Q4"}:
                is_q = True
            elif (
                pdate is not None
                and (pdate.month, pdate.day) in quarter_ends
                and ptype not in {"FY", "H1"}
            ):
                is_q = True
            if is_q:
                quarterly.append(eps_f)
            is_fy = ptype == "FY" or (
                pdate is not None and (pdate.month, pdate.day) == (12, 31) and ptype != "H1"
            )
            if is_fy:
                fy_eps = eps_f

        if len(quarterly) >= 4:
            eps_ttm = float(sum(quarterly[-4:]))
        elif fy_eps is not None:
            eps_ttm = fy_eps
        else:
            eps_ttm = latest_eps

        row: dict[str, object] = {"eps_ttm": eps_ttm}
        row[ent] = entity_key
        rows.append(row)

    return pl.DataFrame(rows) if rows else pl.DataFrame()


def ep_from_pe(pe: pl.Expr) -> pl.Expr:
    """Earnings yield = 1 / PE; null when PE is null or zero."""
    return pl.when(pe.is_not_null() & (pe != 0)).then(1.0 / pe).otherwise(None)


class EpTtm(Factor):
    """Earnings yield (1 / PE_TTM).

    Resolution order per row:
    1. ``valuations.pe_ttm`` joined on entity + trade_date → ``1/pe_ttm``
    2. ``prices.pe_ttm`` column if present
    3. TTM EPS from PIT-filtered ``financials`` / close
    """

    code = "ep_ttm"
    name = "earnings yield TTM"
    category = "value"
    lookback_days = 0
    required_columns = ["close"]

    def _compute(self, prices: pl.DataFrame, data: FactorInput) -> pl.Series:
        ent = entity_col(prices)
        n = prices.height

        if data.valuations is not None and not data.valuations.is_empty():
            val = data.valuations
            require_columns(val, [ent, "trade_date", "pe_ttm"], context="valuations")
            joined = prices.join(
                val.select([ent, "trade_date", "pe_ttm"]),
                on=[ent, "trade_date"],
                how="left",
            )
            return joined.select(ep_from_pe(pl.col("pe_ttm")).alias("_ep")).get_column("_ep")

        if "pe_ttm" in prices.columns:
            return prices.select(ep_from_pe(pl.col("pe_ttm")).alias("_ep")).get_column("_ep")

        if data.financials is None or data.financials.is_empty():
            raise FactorError("ep_ttm requires valuations.pe_ttm, prices.pe_ttm, or financials")

        eps_ttm = ttm_eps_from_financials(data.financials, as_of=data.as_of)
        if eps_ttm.is_empty() or "eps_ttm" not in eps_ttm.columns:
            return pl.Series("_ep", [None] * n, dtype=pl.Float64)

        join_cols = [c for c in (ent,) if c in eps_ttm.columns]
        joined = prices.join(eps_ttm.select([*join_cols, "eps_ttm"]), on=join_cols, how="left")
        return joined.select(
            pl.when(pl.col("close").is_not_null() & (pl.col("close") != 0))
            .then(pl.col("eps_ttm") / pl.col("close"))
            .otherwise(None)
            .alias("_ep")
        ).get_column("_ep")


def compute_ep_ttm_pit(
    prices: pl.DataFrame,
    financials: pl.DataFrame,
    *,
    as_of: date,
) -> pl.DataFrame:
    """Convenience for PIT tests: EP from financials visible at ``as_of``."""
    factor = EpTtm()
    data = FactorInput(
        prices=sorted_prices(prices),
        financials=financials,
        as_of=as_of,
    )
    return factor.compute_frame(data)
