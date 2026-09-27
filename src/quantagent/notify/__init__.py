"""P2a notify package."""

from quantagent.notify.base import AlertMessage, DeliveryResult, LogNotifier, NotifierAdapter
from quantagent.notify.factory import build_notifier
from quantagent.notify.formatter import (
    format_alert,
    format_pushplus_content,
    format_telegram_text,
    format_wecom_markdown,
)
from quantagent.notify.pushplus import PushPlusNotifier
from quantagent.notify.telegram import TelegramNotifier
from quantagent.notify.wecom import WeComWebhookNotifier

__all__ = [
    "AlertMessage",
    "DeliveryResult",
    "LogNotifier",
    "NotifierAdapter",
    "PushPlusNotifier",
    "TelegramNotifier",
    "WeComWebhookNotifier",
    "build_notifier",
    "format_alert",
    "format_pushplus_content",
    "format_telegram_text",
    "format_wecom_markdown",
]
