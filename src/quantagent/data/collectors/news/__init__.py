"""News / announcement collectors (akshare-backed flash + notices)."""

from quantagent.data.collectors.news.announcement import (
    EmAnnouncementCollector,
    fetch_em_notice_report,
)
from quantagent.data.collectors.news.cls import ClsNewsCollector
from quantagent.data.collectors.news.em import EmNewsCollector

__all__ = [
    "ClsNewsCollector",
    "EmAnnouncementCollector",
    "EmNewsCollector",
    "fetch_em_notice_report",
]
