"""Loaders package."""

from quantagent.data.loaders.financial import FinancialLoader
from quantagent.data.loaders.industry import IndustryLoader
from quantagent.data.loaders.price import PriceLoader

__all__ = ["FinancialLoader", "IndustryLoader", "PriceLoader"]
