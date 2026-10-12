"""Baostock collectors."""

from quantagent.data.collectors.baostock.adjust import BaostockAdjustCollector
from quantagent.data.collectors.baostock.calendar import BaostockCalendarCollector
from quantagent.data.collectors.baostock.index_constituents import (
    BaostockIndexConstituentCollector,
)
from quantagent.data.collectors.baostock.price import BaostockPriceCollector
from quantagent.data.collectors.baostock.valuation import BaostockValuationCollector

__all__ = [
    "BaostockAdjustCollector",
    "BaostockCalendarCollector",
    "BaostockIndexConstituentCollector",
    "BaostockPriceCollector",
    "BaostockValuationCollector",
]
