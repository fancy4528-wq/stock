"""Loaders package."""

from quantagent.data.loaders.calendar import CalendarLoader
from quantagent.data.loaders.financial import FinancialLoader
from quantagent.data.loaders.industry import IndustryLoader
from quantagent.data.loaders.price import PriceLoader

__all__ = ["CalendarLoader", "FinancialLoader", "IndustryLoader", "PriceLoader"]
