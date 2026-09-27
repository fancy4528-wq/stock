"""Unit tests: notify formatter + log / wecom notifiers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from quantagent.monitor.types import TriggerHit
from quantagent.notify.base import LogNotifier
from quantagent.notify.formatter import (
    format_alert,
    format_pushplus_content,
    format_telegram_text,
    format_wecom_markdown,
)
from quantagent.notify.pushplus import PushPlusNotifier
from quantagent.notify.wecom import WeComWebhookNotifier


def test_format_alert_and_telegram() -> None:
    hit = TriggerHit(
        code="PX_STOP_LOSS",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="茅台 浮亏 12%",
        evidence={"holding_return": -0.12},
    )
    alert = format_alert(hit)
    assert alert.trigger_codes == ["PX_STOP_LOSS"]
    assert alert.cost_usd == 0.0
    text = format_telegram_text(alert)
    assert "PX_STOP_LOSS" in text
    assert "L1" in text


def test_format_wecom_markdown() -> None:
    hit = TriggerHit(
        code="PX_STOP_LOSS",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="茅台 浮亏 12%",
        evidence={"holding_return": -0.12},
    )
    text = format_wecom_markdown(format_alert(hit))
    assert "PX_STOP_LOSS" in text
    assert "600519.SH" in text
    assert "warning" in text


def test_format_pushplus_content() -> None:
    hit = TriggerHit(
        code="PX_STOP_LOSS",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="茅台 浮亏 12%",
    )
    text = format_pushplus_content(format_alert(hit))
    assert "PX_STOP_LOSS" in text
    assert "600519.SH" in text
    assert "critical" in text


def test_log_notifier() -> None:
    hit = TriggerHit(
        code="PX_LIMIT_DOWN",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="跌停",
    )
    alert = format_alert(hit)
    result = asyncio.run(LogNotifier().send(alert))
    assert result.ok
    assert result.channel == "log"


def test_wecom_notifier_ok() -> None:
    hit = TriggerHit(
        code="ANN_CRITICAL/1",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="立案调查",
    )
    alert = format_alert(hit)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"errcode":0,"errmsg":"ok"}'
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("quantagent.notify.wecom.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(
            WeComWebhookNotifier(
                webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"
            ).send(alert)
        )
    assert result.ok
    assert result.channel == "wecom"
    mock_client.post.assert_awaited_once()
    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["msgtype"] == "markdown"
    assert "ANN" in payload["markdown"]["content"] or "立案" in payload["markdown"]["content"]


def test_wecom_notifier_errcode() -> None:
    hit = TriggerHit(
        code="PX_VOL_SPIKE",
        severity="high",
        symbol="000858.SZ",
        title="t",
        message="放量",
    )
    alert = format_alert(hit)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"errcode":93000,"errmsg":"invalid webhook url"}'
    mock_resp.json.return_value = {"errcode": 93000, "errmsg": "invalid webhook url"}
    mock_resp.text = "invalid webhook url"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("quantagent.notify.wecom.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(
            WeComWebhookNotifier(webhook_url="https://example.com/hook").send(alert)
        )
    assert not result.ok
    assert "invalid" in result.detail.lower() or "93000" in result.detail


def test_pushplus_notifier_ok() -> None:
    hit = TriggerHit(
        code="ANN_CRITICAL/1",
        severity="critical",
        symbol="600519.SH",
        title="t",
        message="立案调查",
    )
    alert = format_alert(hit)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"code":200,"msg":"ok","data":"abc123"}'
    mock_resp.json.return_value = {"code": 200, "msg": "ok", "data": "abc123"}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("quantagent.notify.pushplus.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(PushPlusNotifier(token="tok_test").send(alert))
    assert result.ok
    assert result.channel == "pushplus"
    assert result.message_id == "abc123"
    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["token"] == "tok_test"
    assert payload["template"] == "markdown"
    assert payload["channel"] == "wechat"
    assert "ANN" in payload["content"] or "立案" in payload["title"]


def test_pushplus_notifier_fail_code() -> None:
    hit = TriggerHit(
        code="PX_VOL_SPIKE",
        severity="high",
        symbol="000858.SZ",
        title="t",
        message="放量",
    )
    alert = format_alert(hit)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"code":500,"msg":"token error"}'
    mock_resp.json.return_value = {"code": 500, "msg": "token error"}
    mock_resp.text = "token error"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("quantagent.notify.pushplus.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(PushPlusNotifier(token="bad").send(alert))
    assert not result.ok
    assert "token" in result.detail.lower() or "500" in result.detail


def test_pushplus_send_digest_one_request() -> None:
    alerts = [
        format_alert(
            TriggerHit(
                code="PX_STOP_LOSS",
                severity="critical",
                symbol="600519.SH",
                title="t",
                message="止损",
            )
        ),
        format_alert(
            TriggerHit(
                code="PX_TAKE_PROFIT",
                severity="high",
                symbol="000858.SZ",
                title="t",
                message="止盈",
            )
        ),
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"code":200,"msg":"ok","data":"d1"}'
    mock_resp.json.return_value = {"code": 200, "msg": "ok", "data": "d1"}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("quantagent.notify.pushplus.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(PushPlusNotifier(token="tok").send_digest(alerts))
    assert result.ok
    mock_client.post.assert_awaited_once()
    payload = mock_client.post.await_args.kwargs["json"]
    assert "×2" in payload["title"] or "2" in payload["title"]
    assert "止损" in payload["content"] or "PX_STOP_LOSS" in payload["content"]
    assert "止盈" in payload["content"] or "PX_TAKE_PROFIT" in payload["content"]
