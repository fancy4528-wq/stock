"""Feature / factor library (P1 MVP + P3 expansion)."""

from quantagent.quant.features.base import Factor, FactorError, FactorInput
from quantagent.quant.features.compute import build_factor_panel, compute_factors
from quantagent.quant.features.registry import (
    ALL_FACTOR_CODES,
    ALL_FACTORS,
    L1_SYNTHETIC_CODES,
    MVP_FACTOR_CODES,
    MVP_FACTORS,
    P3_BATCH_CODES,
    P3_BATCH_FACTORS,
    get_factor,
    list_factors,
)
from quantagent.quant.features.transform import (
    DEFAULT_TRANSFORM,
    TransformConfig,
    attach_cs_covariates,
    estimate_log_mktcap,
    neutralize,
    rank_pct,
    transform_cross_section,
    winsorize_mad,
)
from quantagent.quant.features.value import (
    compute_ep_ttm_pit,
    filter_financials_as_of,
    ttm_eps_from_financials,
)

__all__ = [
    "ALL_FACTOR_CODES",
    "ALL_FACTORS",
    "DEFAULT_TRANSFORM",
    "Factor",
    "FactorError",
    "FactorInput",
    "L1_SYNTHETIC_CODES",
    "MVP_FACTOR_CODES",
    "MVP_FACTORS",
    "P3_BATCH_CODES",
    "P3_BATCH_FACTORS",
    "TransformConfig",
    "attach_cs_covariates",
    "build_factor_panel",
    "compute_ep_ttm_pit",
    "compute_factors",
    "estimate_log_mktcap",
    "filter_financials_as_of",
    "get_factor",
    "list_factors",
    "neutralize",
    "rank_pct",
    "transform_cross_section",
    "ttm_eps_from_financials",
    "winsorize_mad",
]
