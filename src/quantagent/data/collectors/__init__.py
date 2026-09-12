"""Collector package."""

from quantagent.data.collectors.baostock import (
    BaostockAdjustCollector,
    BaostockCalendarCollector,
    BaostockPriceCollector,
)
from quantagent.data.collectors.base import Collector, RawBatch

__all__ = [
    "BaostockAdjustCollector",
    "BaostockCalendarCollector",
    "BaostockPriceCollector",
    "Collector",
    "RawBatch",
]
