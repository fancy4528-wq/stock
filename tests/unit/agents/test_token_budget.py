"""TokenBudget pre-call reserve + allocation isolation."""

from __future__ import annotations

import pytest

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.config import BudgetConfig, LLMConfig, TierConfig
from quantagent.shared.errors import BudgetDegrade, BudgetExceeded, BudgetSkip


def _cfg(*, research: float = 0.01, adhoc: float = 0.01) -> LLMConfig:
    tiers = {
        "small": TierConfig(
            model="m-small",
            max_tokens_out=100,
            input_usd_per_1m=1_000.0,
            output_usd_per_1m=1_000.0,
        ),
        "medium": TierConfig(
            model="m-med",
            max_tokens_out=100,
            input_usd_per_1m=1_000.0,
            output_usd_per_1m=1_000.0,
        ),
    }
    budget = BudgetConfig(
        daily_usd_limit=1.0,
        allocations={
            "daily_research": research,
            "monitoring": 0.50,
            "news_extraction": 0.50,
            "adhoc": adhoc,
        },
        on_exceed={
            "daily_research": "degrade",
            "monitoring": "l1_only",
            "news_extraction": "skip",
            "adhoc": "abort",
        },
        per_call_max_tokens_in=50_000,
        per_call_max_tokens_out=4_000,
    )
    return LLMConfig(tiers=tiers, budget=budget)


def test_reserve_and_settle_charges_actual() -> None:
    budget = TokenBudget(llm_config=_cfg(research=1.0))
    # 1000 in + 1000 out at $1000/1M = $1.00 estimated with out_cap
    res = budget.check_and_reserve("daily_research", 500, 100, "medium")
    assert res.reserved_usd > 0
    assert budget.reserved("daily_research") == pytest.approx(res.reserved_usd)
    actual = budget.settle(res, prompt_tokens=100, completion_tokens=50, cost_usd=0.05)
    assert actual == pytest.approx(0.05)
    assert budget.spent("daily_research") == pytest.approx(0.05)
    assert budget.reserved("daily_research") == pytest.approx(0.0)


def test_allocations_do_not_cross_borrow() -> None:
    budget = TokenBudget(llm_config=_cfg(research=0.001, adhoc=1.0))
    # Tiny research pool: 10 tokens in+out at $1000/1M = $0.02 > 0.001
    with pytest.raises(BudgetDegrade):
        budget.check_and_reserve("daily_research", 10, 10, "medium")
    # monitoring / adhoc still usable
    res = budget.check_and_reserve("adhoc", 10, 10, "medium")
    assert res.allocation == "adhoc"
    budget.release(res)


def test_adhoc_abort_raises_budget_exceeded() -> None:
    budget = TokenBudget(llm_config=_cfg(adhoc=0.0001))
    with pytest.raises(BudgetExceeded):
        budget.check_and_reserve("adhoc", 100, 100, "medium")


def test_news_extraction_skip() -> None:
    cfg = _cfg()
    cfg.budget.allocations["news_extraction"] = 0.0001
    budget = TokenBudget(llm_config=cfg)
    with pytest.raises(BudgetSkip) as exc:
        budget.check_and_reserve("news_extraction", 100, 100, "medium")
    assert exc.value.action == "skip"


def test_per_call_token_cap_refuses() -> None:
    budget = TokenBudget(llm_config=_cfg(research=10.0))
    with pytest.raises(BudgetExceeded, match="per_call_max_tokens_in"):
        budget.check_and_reserve("daily_research", 60_000, 10, "medium")


def test_release_on_failure_path() -> None:
    budget = TokenBudget(llm_config=_cfg(research=1.0))
    res = budget.check_and_reserve("daily_research", 10, 10, "medium")
    assert budget.reserved("daily_research") > 0
    budget.release(res)
    assert budget.reserved("daily_research") == pytest.approx(0.0)
    assert budget.spent("daily_research") == pytest.approx(0.0)
