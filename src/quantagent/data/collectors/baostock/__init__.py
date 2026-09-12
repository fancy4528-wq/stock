"""Baostock collectors."""

from quantagent.data.collectors.baostock.adjust import BaostockAdjustCollector
from quantagent.data.collectors.baostock.calendar import BaostockCalendarCollector
from quantagent.data.collectors.baostock.price import BaostockPriceCollector

__all__ = ["BaostockAdjustCollector", "BaostockCalendarCollector", "BaostockPriceCollector"]
