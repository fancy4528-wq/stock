"""企业微信群机器人 notifier（国内免 VPN）。"""

from __future__ import annotations

import logging

import httpx

from quantagent.notify.base import AlertMessage, DeliveryResult, NotifierAdapter
from quantagent.notify.formatter import format_wecom_markdown

logger = logging.getLogger(__name__)


class WeComWebhookNotifier(NotifierAdapter):
    """Send via 企业微信 group robot webhook (msgtype=markdown)."""

    def __init__(self, *, webhook_url: str, timeout: float = 15.0) -> None:
        self._url = webhook_url.strip()
        self._timeout = timeout

    def supports_interactive(self) -> bool:
        return False

    async def send(self, alert: AlertMessage) -> DeliveryResult:
        payload: dict[str, object] = {
            "msgtype": "markdown",
            "markdown": {"content": format_wecom_markdown(alert)},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload)
                data = resp.json() if resp.content else {}
                errcode = (
                    int(data.get("errcode", 0))
                    if isinstance(data, dict) and data.get("errcode") is not None
                    else 0
                )
                if resp.status_code >= 400 or errcode != 0:
                    detail = str(
                        (data.get("errmsg") if isinstance(data, dict) else None) or resp.text
                    )[:300]
                    logger.warning("wecom send failed: %s", detail)
                    return DeliveryResult(ok=False, channel="wecom", detail=detail)
                return DeliveryResult(ok=True, channel="wecom", detail="ok")
        except Exception as exc:  # noqa: BLE001
            logger.warning("wecom send error: %s", exc)
            return DeliveryResult(ok=False, channel="wecom", detail=f"{type(exc).__name__}: {exc}")
