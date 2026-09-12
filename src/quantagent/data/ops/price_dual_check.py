"""Shared dual-source price validation (PX_009) for ingest paths."""

from __future__ import annotations

from datetime import date

import polars as pl
from sqlalchemy.engine import Engine

from quantagent.data.validators import ValidationContext, Validator
from quantagent.data.validators.price_dual import attach_peer_closes
from quantagent.data.validators.report import ValidationReport


def validate_prices_dual(
    primary: pl.DataFrame,
    peer: pl.DataFrame,
    *,
    check_date: date,
    engine: Engine | None = None,
    persist: bool = False,
    run_id: str | None = None,
) -> ValidationReport:
    """Attach peer closes and run ``price_daily`` rules (exercises PX_009)."""
    dual_df = attach_peer_closes(primary, peer)
    ctx = ValidationContext(
        check_date=check_date,
        persist=persist,
        extra={"run_id": run_id} if run_id else None,
    )
    report = Validator(engine).validate(dual_df, "price_daily", ctx)
    for result in report.results:
        if result.code == "PX_009" and result.status != "pass":
            level = result.level
            print(f"price dual-check {level}: {result.detail} affected={result.affected_count}")
            if result.affected_keys:
                print(f"  sample: {result.affected_keys[:5]}")
    return report
