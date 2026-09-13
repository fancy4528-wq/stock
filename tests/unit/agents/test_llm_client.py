"""HttpLLMClient + complete_with_budget (mocked HTTP)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.call import complete_with_budget
from quantagent.agents.llm.client import EchoLLMClient
from quantagent.agents.llm.config import BudgetConfig, LLMConfig, TierConfig
from quantagent.agents.llm.factory import build_llm_client
from quantagent.agents.llm.http_client import HttpLLMClient, LLMHTTPError
from quantagent.agents.llm.pricing import estimate_tokens


def _llm_cfg() -> LLMConfig:
    return LLMConfig(
        tiers={
            "medium": TierConfig(
                model="test-model",
                base_url="https://example.test/v1",
                max_tokens_out=64,
                input_usd_per_1m=1.0,
                output_usd_per_1m=2.0,
            )
        },
        budget=BudgetConfig(
            allocations={
                "daily_research": 1.0,
                "monitoring": 0.5,
                "news_extraction": 0.5,
                "adhoc": 0.1,
            }
        ),
    )


@pytest.mark.asyncio
async def test_http_llm_client_parses_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _llm_cfg()
    client = HttpLLMClient(api_key="sk-test", config=cfg, default_tier="medium")

    class _FakeResp:
        status_code = 200
        text = "ok"

        def json(self) -> dict[str, Any]:
            return {
                "model": "test-model",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }

    class _FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = (args, kwargs)

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> _FakeResp:
            assert url.endswith("/chat/completions")
            assert headers["Authorization"] == "Bearer sk-test"
            assert json["model"] == "test-model"
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    resp = await client.complete(system="s", user="u")
    assert resp.text == '{"ok": true}'
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 4
    assert resp.cost_usd == pytest.approx(12 * 1.0 / 1e6 + 4 * 2.0 / 1e6)


@pytest.mark.asyncio
async def test_http_llm_client_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _llm_cfg()
    client = HttpLLMClient(api_key="sk-test", config=cfg, default_tier="medium")

    class _FakeResp:
        status_code = 500
        text = "boom"

        def json(self) -> dict[str, Any]:
            return {}

    class _FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = (args, kwargs)

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def post(self, *args: object, **kwargs: object) -> _FakeResp:
            _ = (args, kwargs)
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    with pytest.raises(LLMHTTPError, match="500"):
        await client.complete(system="s", user="u")


@pytest.mark.asyncio
async def test_complete_with_budget_settles() -> None:
    budget = TokenBudget(llm_config=_llm_cfg())
    llm = EchoLLMClient('{"hello":1}')
    resp, res = await complete_with_budget(
        llm,
        budget,
        allocation="daily_research",
        tier="medium",
        system="sys",
        user="user payload",
    )
    assert resp.text.startswith("{")
    assert res.settled
    assert budget.spent("daily_research") == pytest.approx(resp.cost_usd)


def test_build_llm_client_null_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from quantagent.shared.config.settings import get_settings

    get_settings.cache_clear()
    client = build_llm_client(api_key="")
    assert client.model == "null"
    get_settings.cache_clear()


def test_estimate_tokens_cjk() -> None:
    assert estimate_tokens("你好世界") == 4
    assert estimate_tokens("abcd") == 1
