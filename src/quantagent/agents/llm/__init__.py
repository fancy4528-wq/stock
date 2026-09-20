"""LLM client + token metering + ADR-0010 budget."""

from quantagent.agents.llm.budget import BudgetReservation, DegradationNote, TokenBudget
from quantagent.agents.llm.call import complete_with_budget
from quantagent.agents.llm.client import EchoLLMClient, LLMClient, LLMResponse, NullLLMClient
from quantagent.agents.llm.config import BudgetConfig, LLMConfig, TierConfig, load_llm_config
from quantagent.agents.llm.factory import build_llm_client, build_token_budget
from quantagent.agents.llm.http_client import HttpLLMClient, LLMHTTPError
from quantagent.agents.llm.metering import CostRecord, CostTracker
from quantagent.agents.llm.pricing import estimate_prompt_tokens, estimate_tokens, price_usd
from quantagent.agents.llm.structured import (
    ResearchLlmBundle,
    complete_research_json,
    complete_research_model,
    extract_json_object,
    llm_enabled,
)

__all__ = [
    "BudgetConfig",
    "BudgetReservation",
    "CostRecord",
    "CostTracker",
    "DegradationNote",
    "EchoLLMClient",
    "HttpLLMClient",
    "LLMClient",
    "LLMConfig",
    "LLMHTTPError",
    "LLMResponse",
    "NullLLMClient",
    "ResearchLlmBundle",
    "TierConfig",
    "TokenBudget",
    "build_llm_client",
    "build_token_budget",
    "complete_research_json",
    "complete_research_model",
    "complete_with_budget",
    "estimate_prompt_tokens",
    "estimate_tokens",
    "extract_json_object",
    "llm_enabled",
    "load_llm_config",
    "price_usd",
]
