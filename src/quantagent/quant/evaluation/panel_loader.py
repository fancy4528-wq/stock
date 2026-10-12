"""Load real OHLCV (+ optional valuation) panels for L1 evaluation."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from quantagent.core.universe import (
    active_survivorship_symbols,
    load_universe_config,
)
from quantagent.quant.features.base import FactorError, FactorInput
from quantagent.quant.features.registry import ALL_FACTOR_CODES
from quantagent.shared.errors import QuantAgentError

if TYPE_CHECKING:
    from quantagent.core.repository.pit import PITRepository

# Value yields need valuation_daily (or pe/pb/ps columns on the price panel).
VALUE_FACTOR_CODES: frozenset[str] = frozenset({"ep_ttm", "bp", "sp_ttm"})

_PRICE_FLOAT_COLS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "amount",
    "turnover_rate",
    "volume",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "market_cap",
    "circ_market_cap",
    "dividend_yield",
)


class PanelLoadError(QuantAgentError):
    """Failed to build a real-data L1 panel from the database."""


def cast_panel_floats(df: pl.DataFrame) -> pl.DataFrame:
    """Cast Decimal / numeric OHLCV columns to Float64 for factor math."""
    if df.is_empty():
        return df
    casts: list[pl.Expr] = []
    for col in _PRICE_FLOAT_COLS:
        if col not in df.columns:
            continue
        dtype = df.schema[col]
        if dtype == pl.Float64:
            continue
        casts.append(pl.col(col).cast(pl.Float64, strict=False))
    return df.with_columns(casts) if casts else df


def resolve_universe_symbols(
    *,
    universe: str = "mvp_cn_50",
    as_of: date,
    repo: PITRepository | None = None,
) -> list[str]:
    """Symbols for L1: PIT universe @ as_of ∪ bootstrap ∪ active survivorship probes.

    Only returns symbols that exist in ``security`` (so ``get_prices`` won't raise).
    """
    from quantagent.core.repository.pit import PITRepository

    pit = repo or PITRepository()
    cfg = load_universe_config(universe)
    wanted: list[str] = []

    snap = pit.get_universe(as_of=as_of, name=universe)
    if not snap.is_empty() and "symbol" in snap.columns:
        wanted.extend(str(s) for s in snap["symbol"].to_list() if s)

    wanted.extend(cfg.bootstrap_symbols)
    wanted.extend(active_survivorship_symbols(cfg, as_of))

    # Historical members (monthly snapshots) — reduces fixed-list survivorship bias a bit.
    with pit._engine.connect() as conn:
        hist = conn.execute(
            text(
                """
                SELECT DISTINCT s.symbol
                FROM universe_snapshot us
                JOIN universe u ON u.universe_id = us.universe_id
                JOIN security s ON s.security_id = us.security_id
                WHERE u.code = :code
                  AND us.snapshot_date <= :as_of
                ORDER BY s.symbol
                """
            ),
            {"code": universe, "as_of": as_of},
        ).fetchall()
    wanted.extend(str(r[0]) for r in hist if r[0])

    deduped = list(dict.fromkeys(wanted))
    if not deduped:
        raise PanelLoadError(f"no symbols for universe={universe!r} as_of={as_of}")

    with pit._engine.connect() as conn:
        stmt = text(
            "SELECT symbol FROM security WHERE symbol = ANY(:symbols) ORDER BY symbol"
        ).bindparams(bindparam("symbols", type_=ARRAY(TEXT())))
        rows = conn.execute(stmt, {"symbols": deduped}).fetchall()
    available = [str(r[0]) for r in rows]
    if not available:
        raise PanelLoadError(
            f"none of {len(deduped)} universe symbols exist in security "
            f"(universe={universe!r})"
        )
    return available


def load_l1_factor_input(
    *,
    universe: str = "mvp_cn_50",
    start: date,
    end: date | None = None,
    as_of: date | None = None,
    adjust: str = "qfq",
    symbols: list[str] | None = None,
    repo: PITRepository | None = None,
) -> FactorInput:
    """Build a PIT-safe :class:`FactorInput` from ``price_daily`` (+ valuation if any).

    Prices come from ``get_prices_as_of`` (qfq when ``adjust_factor`` rows exist;
    otherwise raw closes with factor=1). Valuation join is optional — empty table
    means value factors are skipped by :func:`codes_for_real_l1`.
    """
    from quantagent.core.repository.pit import PITRepository

    pit = repo or PITRepository()
    end_date = end or as_of
    if end_date is None:
        raise PanelLoadError("end or as_of is required")
    as_of_date = as_of or end_date
    if end_date > as_of_date:
        end_date = as_of_date

    syms = symbols or resolve_universe_symbols(
        universe=universe, as_of=as_of_date, repo=pit
    )
    prices = pit.get_prices(
        syms,
        as_of=as_of_date,
        start=start,
        end=end_date,
        adjust=adjust,
    )
    if prices.is_empty():
        raise PanelLoadError(
            f"no price_daily rows for universe={universe!r} "
            f"start={start} end={end_date} as_of={as_of_date}"
        )

    prices = cast_panel_floats(prices)
    # Drop helper column from PIT reads; factors do not need it.
    if "_as_of" in prices.columns:
        prices = prices.drop("_as_of")

    valuations: pl.DataFrame | None = None
    val = pit.get_valuation(syms, as_of=as_of_date, start=start, end=end_date)
    if not val.is_empty():
        valuations = cast_panel_floats(val)
        if "_as_of" in valuations.columns:
            valuations = valuations.drop("_as_of")

    # SW L1 membership at as_of (broadcast across the panel calendar; MVP approx).
    industry: pl.DataFrame | None = None
    ind = pit.get_industry(syms, as_of=as_of_date, taxonomy="sw_2021")
    if not ind.is_empty():
        industry = ind
        if "level" in industry.columns:
            l1 = industry.filter(pl.col("level") == 1)
            if not l1.is_empty():
                industry = l1

    return FactorInput(
        prices=prices,
        valuations=valuations,
        industry=industry,
        as_of=as_of_date,
        meta={
            "source": "db",
            "universe": universe,
            "start": start.isoformat(),
            "end": end_date.isoformat(),
            "adjust": adjust,
            "n_symbols": len(syms),
            "n_rows": prices.height,
            "has_valuation": valuations is not None and not valuations.is_empty(),
            "has_industry": industry is not None and not industry.is_empty(),
            "n_industry": 0 if industry is None else industry.height,
        },
    )


def codes_for_real_l1(
    data: FactorInput,
    codes: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (runnable_codes, skipped_codes) given available panels."""
    selected = list(codes) if codes is not None else list(ALL_FACTOR_CODES)
    has_val = data.valuations is not None and not data.valuations.is_empty()
    price_cols = set(data.prices.columns)

    runnable: list[str] = []
    skipped: list[str] = []
    for code in selected:
        if code in VALUE_FACTOR_CODES:
            if has_val:
                runnable.append(code)
                continue
            # Allow pe/pb/ps embedded on the price panel (parquet / synthetic).
            need = {"ep_ttm": "pe_ttm", "bp": "pb", "sp_ttm": "ps_ttm"}[code]
            if need in price_cols:
                runnable.append(code)
            else:
                skipped.append(code)
            continue
        runnable.append(code)

    if not runnable:
        raise FactorError("no runnable L1 factors for this panel")
    return runnable, skipped


def export_l1_price_panel(data: FactorInput, path: str | object) -> None:
    """Write the price panel (and valuation columns if joined) to parquet."""
    from pathlib import Path

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    panel = data.prices
    if data.valuations is not None and not data.valuations.is_empty():
        ent = "security_id" if "security_id" in panel.columns else "symbol"
        val_cols = [
            c
            for c in data.valuations.columns
            if c in (ent, "trade_date", "pe_ttm", "pb", "ps_ttm")
        ]
        panel = panel.join(
            data.valuations.select(val_cols),
            on=[ent, "trade_date"],
            how="left",
        )
    panel.write_parquet(out)
