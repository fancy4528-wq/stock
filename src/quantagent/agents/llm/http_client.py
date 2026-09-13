"""OpenAI-compatible HTTP LLM client (httpx + tenacity)."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.agents.llm.client import LLMResponse
from quantagent.agents.llm.config import LLMConfig, TierConfig, load_llm_config
from quantagent.agents.llm.pricing import price_usd
from quantagent.shared.errors import AgentError, ConfigError


class LLMHTTPError(AgentError):
    """Upstream LLM HTTP / API failure."""


class HttpLLMClient:
    """Chat Completions against an OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        config: LLMConfig | None = None,
        default_tier: str = "medium",
        base_url_override: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ConfigError("HttpLLMClient requires a non-empty API key")
        self._api_key = api_key.strip()
        self._cfg = config or load_llm_config()
        self.default_tier = default_tier
        self._base_url_override = base_url_override.rstrip("/") if base_url_override else None
        self._timeout_s = timeout_s
        tier = self._cfg.tier(default_tier)
        self.model = tier.model

    def tier_config(self, tier: str | None = None) -> TierConfig:
        return self._cfg.tier(tier or self.default_tier)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens_out: int | None = None,
        tier: str | None = None,
    ) -> LLMResponse:
        tier_name = (tier or self.default_tier).strip().lower()
        tcfg = self._cfg.tier(tier_name)
        max_out = max_tokens_out if max_tokens_out is not None else tcfg.max_tokens_out
        base = self._base_url_override or tcfg.base_url.rstrip("/")
        url = f"{base}/chat/completions"
        payload: dict[str, Any] = {
            "model": tcfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_out,
            "temperature": tcfg.temperature,
        }
        data = await self._post(url, payload)
        text = _extract_text(data)
        usage = data.get("usage") if isinstance(data, dict) else None
        prompt_tokens = 0
        completion_tokens = 0
        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = price_usd(tcfg, tokens_in=prompt_tokens, tokens_out=completion_tokens)
        return LLMResponse(
            text=text,
            model=str(data.get("model") or tcfg.model) if isinstance(data, dict) else tcfg.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise LLMHTTPError(f"LLM HTTP {resp.status_code}: {resp.text[:400]}")
        data: Any = resp.json()
        if not isinstance(data, dict):
            raise LLMHTTPError("LLM response JSON is not an object")
        return data


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    return text if isinstance(text, str) else ""
