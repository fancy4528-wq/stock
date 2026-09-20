"""Loaders package."""

from quantagent.data.loaders.adjust import AdjustLoader
from quantagent.data.loaders.calendar import CalendarLoader
from quantagent.data.loaders.chunk import ChunkLoader
from quantagent.data.loaders.event import EventLoader
from quantagent.data.loaders.financial import FinancialLoader
from quantagent.data.loaders.industry import IndustryLoader
from quantagent.data.loaders.news import NewsLoader
from quantagent.data.loaders.price import PriceLoader

__all__ = [
    "AdjustLoader",
    "CalendarLoader",
    "ChunkLoader",
    "EventLoader",
    "FinancialLoader",
    "IndustryLoader",
    "NewsLoader",
    "PriceLoader",
]
