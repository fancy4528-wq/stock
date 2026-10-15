"""L2 equal-weight scores for ``shadow_quant`` (Gate 3 working model)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Final

import polars as pl

from quantagent.quant.evaluation.panel_loader import codes_for_real_l1, load_l1_factor_input
from quantagent.quant.features.base import FactorInput, entity_col
from quantagent.quant.features.compute import build_factor_panel
from quantagent.quant.features.transform import (
    DEFAULT_TRANSFORM,
    TransformConfig,
    attach_cs_covariates,
    transform_cross_section,
)
from quantagent.quant.models.baseline import (
    CSI300_L1_ADMITTED_5Y,
    COMBO_EQUAL,
    combine_equal_weight,
)

if TYPE_CHECKING:
    from quantagent.core.repository.pit import PITRepository

# Frozen component IC means from docs/factor-reports-csi300-5y-l2 (2026-10-14).
# Used for sign alignment only — not re-estimated on the live window (PIT-safe).
CSI300_L2_IC_MEANS_5Y: Final[dict[str, float]] = {
    "max_ret_20d": -0.0473,
    "skew_60d": -0.0277,
    "turnover_20d": -0.0466,
    "vol_60d": -0.0506,
    "ep_ttm": 0.0334,
    "vol_price_corr_20d": -0.0221,
    "bp": 0.0346,
}

# Calendar lookback covering vol_60d / skew_60d + transform warm-up.
DEFAULT_QUANT_LOOKBACK_DAYS: Final[int] = 250


def l2_equal_scores_as_of(
    data: FactorInput,
    *,
    as_of: date | None = None,
    codes: list[str] | tuple[str, ...] | None = None,
    ic_means: dict[str, float] | None = None,
    transform: TransformConfig | bool = DEFAULT_TRANSFORM,
) -> dict[str, float]:
    """Cross-section of sign-aligned equal-weight L2 scores on ``as_of``.

    Keys are ``symbol`` when present, else the panel entity column.
    """
    selected = list(codes) if codes is not None else list(CSI300_L1_ADMITTED_5Y)
    means = dict(ic_means) if ic_means is not None else dict(CSI300_L2_IC_MEANS_5Y)
    runnable, _skipped = codes_for_real_l1(data, selected)
    if not runnable:
        return {}

    cfg = (
        transform
        if isinstance(transform, TransformConfig)
        else TransformConfig(enabled=bool(transform))
    )
    panel = build_factor_panel(data, codes=runnable)
    if cfg.enabled:
        panel = attach_cs_covariates(panel, data)
        panel = transform_cross_section(panel, runnable, config=cfg)
    panel = combine_equal_weight(panel, runnable, means, out_col=COMBO_EQUAL)

    day = as_of or data.as_of
    key = "symbol" if "symbol" in panel.columns else entity_col(panel)
    rows = (
        panel.filter(pl.col("trade_date") == day)
        .select([key, COMBO_EQUAL])
        .drop_nulls(subset=[COMBO_EQUAL])
    )
    out: dict[str, float] = {}
    for row in rows.iter_rows(named=True):
        out[str(row[key])] = float(row[COMBO_EQUAL])
    return out


def load_l2_equal_scores(
    *,
    as_of: date,
    universe: str,
    repo: PITRepository | None = None,
    lookback_days: int = DEFAULT_QUANT_LOOKBACK_DAYS,
    transform: TransformConfig | bool = DEFAULT_TRANSFORM,
) -> dict[str, float]:
    """Load PIT panels and return L2 equal-weight scores for ``as_of``."""
    start = as_of - timedelta(days=lookback_days)
    data = load_l1_factor_input(
        universe=universe,
        start=start,
        end=as_of,
        as_of=as_of,
        repo=repo,
    )
    return l2_equal_scores_as_of(data, as_of=as_of, transform=transform)
