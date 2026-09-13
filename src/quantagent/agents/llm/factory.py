"""Factory: NullLLMClient when no key; HttpLLMClient otherwise."""

from __future__ import annotations

from datetime import date

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.client import LLMClient, NullLLMClient
from quantagent.agents.llm.config import load_llm_config
from quantagent.agents.llm.http_client import HttpLLMClient
from quantagent.shared.config.settings import get_settings


def build_llm_client(
    *,
    api_key: str | None = None,
    tier: str | None = None,
    base_url: str | None = None,
) -> LLMClient:
    """Return a live HTTP client when ``LLM_API_KEY`` is set; else Null (deterministic)."""
    settings = get_settings()
    key = (api_key if api_key is not None else settings.llm_api_key) or ""
    key = key.strip()
    if not key:
        return NullLLMClient()
    cfg = load_llm_config()
    default_tier = (tier or settings.llm_default_tier or "medium").strip().lower()
    override = base_url if base_url is not None else settings.llm_base_url
    return HttpLLMClient(
        api_key=key,
        config=cfg,
        default_tier=default_tier,
        base_url_override=override,
    )


def build_token_budget(*, day: date | None = None) -> TokenBudget:
    return TokenBudget(llm_config=load_llm_config(), day=day)
