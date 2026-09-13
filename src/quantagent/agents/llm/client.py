"""LLM client protocol + Null / Echo doubles (HTTP lives in http_client)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens_out: int | None = None,
        tier: str | None = None,
    ) -> LLMResponse: ...


class NullLLMClient:
    """No network. Signals callers to use deterministic summarization."""

    model = "null"

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens_out: int | None = None,
        tier: str | None = None,
    ) -> LLMResponse:
        _ = (system, user, max_tokens_out, tier)
        return LLMResponse(text="", model=self.model, cost_usd=0.0)


class EchoLLMClient:
    """Test double that echoes a fixed JSON payload."""

    def __init__(self, text: str, *, model: str = "echo") -> None:
        self.model = model
        self._text = text

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens_out: int | None = None,
        tier: str | None = None,
    ) -> LLMResponse:
        _ = (max_tokens_out, tier)
        n = max(1, (len(system) + len(user)) // 4)
        return LLMResponse(
            text=self._text,
            model=self.model,
            prompt_tokens=n,
            completion_tokens=max(1, len(self._text) // 4),
            cost_usd=0.001,
        )
