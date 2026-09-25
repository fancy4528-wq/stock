"""Telegram Bot notifier (P2a)."""

from __future__ import annotations

import logging

import httpx

from quantagent.notify.base import AlertMessage, DeliveryResult, NotifierAdapter
from quantagent.notify.formatter import format_telegram_text
from quantagent.shared.config import get_settings

logger = logging.getLogger(__name__)


class TelegramNotifier(NotifierAdapter):
    """Send alerts via Bot API ``sendMessage``."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        timeout: float = 15.0,
        with_feedback_buttons: bool = True,
    ) -> None:
        self._token = bot_token.strip()
        self._chat_id = str(chat_id).strip()
        self._timeout = timeout
        self._with_buttons = with_feedback_buttons

    def supports_interactive(self) -> bool:
        return self._with_buttons

    async def send(self, alert: AlertMessage) -> DeliveryResult:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": format_telegram_text(alert),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self._with_buttons:
            # Bind alert_id into callback for later feedback routing.
            kb = {
                "inline_keyboard": [
                    [
                        {
                            "text": "👍 有用",
                            "callback_data": f"fb:useful:{alert.alert_id}"[:64],
                        },
                        {
                            "text": "👎 没用",
                            "callback_data": f"fb:not_useful:{alert.alert_id}"[:64],
                        },
                        {
                            "text": "🔇 静音24h",
                            "callback_data": f"fb:mute24:{alert.alert_id}"[:64],
                        },
                    ]
                ]
            }
            payload["reply_markup"] = kb

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                data = resp.json()
                if resp.status_code >= 400 or not data.get("ok"):
                    detail = str(data.get("description") or resp.text)[:300]
                    logger.warning("telegram send failed: %s", detail)
                    return DeliveryResult(ok=False, channel="telegram", detail=detail)
                msg_id = str((data.get("result") or {}).get("message_id") or "")
                return DeliveryResult(
                    ok=True, channel="telegram", detail="ok", message_id=msg_id or None
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram send error: %s", exc)
            return DeliveryResult(
                ok=False, channel="telegram", detail=f"{type(exc).__name__}: {exc}"
            )


def build_notifier() -> NotifierAdapter:
    """Telegram if credentials set; otherwise LogNotifier."""
    from quantagent.notify.base import LogNotifier

    settings = get_settings()
    token = (settings.telegram_bot_token or "").strip()
    chat = (settings.telegram_chat_id or "").strip()
    if token and chat:
        return TelegramNotifier(bot_token=token, chat_id=chat)
    return LogNotifier()
