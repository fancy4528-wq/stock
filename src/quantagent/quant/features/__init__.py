"""Feature / factor library (P1 W5)."""

from quantagent.quant.features.base import Factor, FactorError, FactorInput
from quantagent.quant.features.compute import compute_factors
from quantagent.quant.features.registry import MVP_FACTOR_CODES, MVP_FACTORS, get_factor
from quantagent.quant.features.value import (
    compute_ep_ttm_pit,
    filter_financials_as_of,
    ttm_eps_from_financials,
)

__all__ = [
    "Factor",
    "FactorError",
    "FactorInput",
    "MVP_FACTOR_CODES",
    "MVP_FACTORS",
    "compute_ep_ttm_pit",
    "compute_factors",
    "filter_financials_as_of",
    "get_factor",
    "ttm_eps_from_financials",
]
