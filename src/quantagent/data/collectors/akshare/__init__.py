"""Akshare collectors."""

from quantagent.data.collectors.akshare.financial import AkshareFinancialCollector
from quantagent.data.collectors.akshare.index import AkshareIndexCollector
from quantagent.data.collectors.akshare.price import AksharePriceCollector

__all__ = [
    "AkshareFinancialCollector",
    "AkshareIndexCollector",
    "AksharePriceCollector",
]
