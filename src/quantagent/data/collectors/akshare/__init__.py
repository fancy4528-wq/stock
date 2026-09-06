"""Akshare collectors."""

from quantagent.data.collectors.akshare.calendar import AkshareCalendarCollector
from quantagent.data.collectors.akshare.financial import AkshareFinancialCollector
from quantagent.data.collectors.akshare.index import AkshareIndexCollector
from quantagent.data.collectors.akshare.industry import AkshareIndustryCollector
from quantagent.data.collectors.akshare.price import AksharePriceCollector

__all__ = [
    "AkshareCalendarCollector",
    "AkshareFinancialCollector",
    "AkshareIndexCollector",
    "AkshareIndustryCollector",
    "AksharePriceCollector",
]
