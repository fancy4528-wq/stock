"""Pick notifier from env: PushPlus → WeCom → Telegram → Log."""

from __future__ import annotations

from quantagent.notify.base import LogNotifier, NotifierAdapter
from quantagent.shared.config import get_settings


def build_notifier() -> NotifierAdapter:
    """Prefer PushPlus (微信), then WeCom, then Telegram, else stdout log."""
    settings = get_settings()

    pushplus = (settings.pushplus_token or "").strip()
    if pushplus:
        from quantagent.notify.pushplus import PushPlusNotifier

        channel = (settings.pushplus_channel or "wechat").strip() or "wechat"
        return PushPlusNotifier(token=pushplus, channel=channel)

    wecom = (settings.wecom_webhook_url or "").strip()
    if wecom:
        from quantagent.notify.wecom import WeComWebhookNotifier

        return WeComWebhookNotifier(webhook_url=wecom)

    token = (settings.telegram_bot_token or "").strip()
    chat = (settings.telegram_chat_id or "").strip()
    if token and chat:
        from quantagent.notify.telegram import TelegramNotifier

        return TelegramNotifier(bot_token=token, chat_id=chat)

    return LogNotifier()
