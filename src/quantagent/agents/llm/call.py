"""Budget-aware LLM complete helper (pre-call reserve → call → settle)."""

from __future__ import annotations

from quantagent.agents.llm.budget import BudgetReservation, TokenBudget
from quantagent.agents.llm.client import LLMClient, LLMResponse
from quantagent.agents.llm.config import load_llm_config
from quantagent.agents.llm.pricing import estimate_prompt_tokens
from quantagent.shared.errors import BudgetDegrade, BudgetExceeded, BudgetSkip


async def complete_with_budget(
    llm: LLMClient,
    budget: TokenBudget,
    *,
    allocation: str,
    tier: str,
    system: str,
    user: str,
    max_tokens_out: int | None = None,
) -> tuple[LLMResponse, BudgetReservation]:
    """Reserve against ``allocation``, call LLM, settle actual cost.

    Raises ``BudgetExceeded`` / ``BudgetDegrade`` / ``BudgetSkip`` before any HTTP call.
    On transport failure after reserve, releases the reservation.
    """
    cfg = load_llm_config()
    tcfg = cfg.tier(tier)
    out_cap = max_tokens_out if max_tokens_out is not None else tcfg.max_tokens_out
    est_in = estimate_prompt_tokens(system=system, user=user)
    reservation = budget.check_and_reserve(allocation, est_in, out_cap, tier)
    try:
        resp = await llm.complete(
            system=system,
            user=user,
            max_tokens_out=out_cap,
            tier=tier,
        )
    except Exception:
        budget.release(reservation)
        raise
    budget.settle(
        reservation,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
        cost_usd=resp.cost_usd,
    )
    return resp, reservation


__all__ = [
    "BudgetDegrade",
    "BudgetExceeded",
    "BudgetSkip",
    "complete_with_budget",
]
