"""PushPlus notifier — 推送到微信（国内免 VPN）。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from quantagent.notify.base import AlertMessage, DeliveryResult, NotifierAdapter
from quantagent.notify.formatter import format_pushplus_content

logger = logging.getLogger(__name__)

_SEND_URL = "https://www.pushplus.plus/send"


class PushPlusNotifier(NotifierAdapter):
    """Send via PushPlus HTTP API (default channel=wechat → 微信服务号/公众号消息).

    Free tier: ≤5 requests/minute and ≤3 identical bodies/hour — prefer
    :meth:`send_digest` for multi-alert monitor cycles.
    """

    def __init__(
        self,
        *,
        token: str,
        channel: str = "wechat",
        timeout: float = 15.0,
    ) -> None:
        self._token = token.strip()
        self._channel = (channel or "wechat").strip() or "wechat"
        self._timeout = timeout

    def supports_interactive(self) -> bool:
        return False

    async def send(self, alert: AlertMessage) -> DeliveryResult:
        return await self._post(
            title=(alert.title or alert.trigger_reason)[:100],
            content=format_pushplus_content(alert),
        )

    async def send_digest(self, alerts: Sequence[AlertMessage]) -> DeliveryResult:
        """One API call for N alerts (avoids PushPlus 5 req/min cap)."""
        if not alerts:
            return DeliveryResult(ok=True, channel="pushplus", detail="empty")
        if len(alerts) == 1:
            return await self.send(alerts[0])
        title = f"监控告警 ×{len(alerts)}"
        blocks = [format_pushplus_content(a) for a in alerts]
        parts = [f"### {a.title}\n\n{body}" for a, body in zip(alerts, blocks, strict=True)]
        content = "\n\n---\n\n".join(parts)
        return await self._post(title=title[:100], content=content)

    async def _post(self, *, title: str, content: str) -> DeliveryResult:
        payload: dict[str, object] = {
            "token": self._token,
            "title": title,
            "content": content,
            "template": "markdown",
            "channel": self._channel,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_SEND_URL, json=payload)
                data = resp.json() if resp.content else {}
                code = data.get("code") if isinstance(data, dict) else None
                if resp.status_code >= 400 or code != 200:
                    detail = str(
                        (data.get("msg") if isinstance(data, dict) else None) or resp.text
                    )[:300]
                    logger.warning("pushplus send failed: %s", detail)
                    return DeliveryResult(ok=False, channel="pushplus", detail=detail)
                msg_id = None
                if isinstance(data, dict) and data.get("data") is not None:
                    msg_id = str(data.get("data"))[:64]
                return DeliveryResult(ok=True, channel="pushplus", detail="ok", message_id=msg_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pushplus send error: %s", exc)
            return DeliveryResult(
                ok=False, channel="pushplus", detail=f"{type(exc).__name__}: {exc}"
            )
