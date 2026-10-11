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
from quantagent.quant.features.value import (
    compute_ep_ttm_pit,
    filter_financials_as_of,
    ttm_eps_from_financials,
)

__all__ = [
    "ALL_FACTOR_CODES",
    "ALL_FACTORS",
    "Factor",
    "FactorError",
    "FactorInput",
    "L1_SYNTHETIC_CODES",
    "MVP_FACTOR_CODES",
    "MVP_FACTORS",
    "P3_BATCH_CODES",
    "P3_BATCH_FACTORS",
    "build_factor_panel",
    "compute_ep_ttm_pit",
    "compute_factors",
    "filter_financials_as_of",
    "get_factor",
    "list_factors",
    "ttm_eps_from_financials",
]
