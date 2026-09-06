"""Minimal LLM client. MVP uses NullLLMClient (deterministic Reporter)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class LLMClient(Protocol):
    model: str

    async def complete(self, *, system: str, user: str) -> LLMResponse: ...


class NullLLMClient:
    """No network. Signals callers to use deterministic summarization."""

    model = "null"

    async def complete(self, *, system: str, user: str) -> LLMResponse:
        _ = (system, user)
        return LLMResponse(text="", model=self.model, cost_usd=0.0)


class EchoLLMClient:
    """Test double that echoes a fixed JSON payload."""

    def __init__(self, text: str, *, model: str = "echo") -> None:
        self.model = model
        self._text = text

    async def complete(self, *, system: str, user: str) -> LLMResponse:
        _ = (system, user)
        # Rough token estimate for metering demos
        n = max(1, (len(system) + len(user)) // 4)
        return LLMResponse(
            text=self._text,
            model=self.model,
            prompt_tokens=n,
            completion_tokens=max(1, len(self._text) // 4),
            cost_usd=0.001,
        )


class TokenBudget(BaseModel):
    remaining_usd: float = Field(default=1.0, ge=0.0)

    def charge(self, usd: float) -> None:
        self.remaining_usd = max(0.0, self.remaining_usd - usd)
