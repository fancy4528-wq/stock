"""ADR-0010 TokenBudget: pre-call reserve, per-allocation pools, settle."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from quantagent.agents.llm.config import BudgetConfig, LLMConfig, load_llm_config
from quantagent.agents.llm.pricing import price_usd_for_tier
from quantagent.shared.errors import BudgetDegrade, BudgetExceeded, BudgetSkip, ConfigError


class DegradationNote(BaseModel):
    allocation: str
    action: str
    reason: str
    impact: str


class BudgetReservation(BaseModel):
    allocation: str
    reserved_usd: float = Field(ge=0.0)
    tier: str
    estimated_tokens_in: int = Field(ge=0)
    estimated_tokens_out: int = Field(ge=0)
    settled: bool = False
    actual_usd: float | None = None

    model_config = {"arbitrary_types_allowed": True}


class TokenBudget:
    """In-process daily budget with independent allocation pools.

    Call ``check_and_reserve`` *before* the LLM HTTP round-trip, then
    ``settle`` with actual usage. Pools never borrow from each other.
    """

    def __init__(
        self,
        budget: BudgetConfig | None = None,
        *,
        llm_config: LLMConfig | None = None,
        day: date | None = None,
    ) -> None:
        self._llm = llm_config or load_llm_config()
        self._cfg = budget or self._llm.budget
        self.day = day or date.today()
        self._spent: dict[str, float] = {name: 0.0 for name in self._cfg.allocations}
        self._reserved: dict[str, float] = {name: 0.0 for name in self._cfg.allocations}
        self.degradations: list[DegradationNote] = []

    @property
    def config(self) -> BudgetConfig:
        return self._cfg

    def spent(self, allocation: str) -> float:
        self._require_allocation(allocation)
        return self._spent[allocation]

    def reserved(self, allocation: str) -> float:
        self._require_allocation(allocation)
        return self._reserved[allocation]

    def remaining(self, allocation: str) -> float:
        self._require_allocation(allocation)
        limit = float(self._cfg.allocations[allocation])
        return max(0.0, limit - self._spent[allocation] - self._reserved[allocation])

    def total_spent_usd(self) -> float:
        return sum(self._spent.values())

    def check_and_reserve(
        self,
        allocation: str,
        estimated_tokens_in: int,
        estimated_tokens_out: int,
        tier: str,
    ) -> BudgetReservation:
        """Pre-call estimate + reserve. Raises BudgetExceeded / BudgetDegrade / BudgetSkip."""
        self._require_allocation(allocation)
        if estimated_tokens_in < 0 or estimated_tokens_out < 0:
            raise ConfigError("estimated token counts must be non-negative")
        if estimated_tokens_in > self._cfg.per_call_max_tokens_in:
            raise BudgetExceeded(
                allocation,
                self._spent[allocation],
                float(self._cfg.allocations[allocation]),
                0.0,
                detail=(
                    f"prompt tokens {estimated_tokens_in} > "
                    f"per_call_max_tokens_in {self._cfg.per_call_max_tokens_in}"
                ),
            )
        out_cap = min(estimated_tokens_out, self._cfg.per_call_max_tokens_out)
        if estimated_tokens_out > self._cfg.per_call_max_tokens_out:
            # Hard refuse oversized max_tokens_out (do not silently truncate).
            raise BudgetExceeded(
                allocation,
                self._spent[allocation],
                float(self._cfg.allocations[allocation]),
                0.0,
                detail=(
                    f"max_tokens_out {estimated_tokens_out} > "
                    f"per_call_max_tokens_out {self._cfg.per_call_max_tokens_out}"
                ),
            )

        est_cost = price_usd_for_tier(
            self._llm,
            tier,
            tokens_in=estimated_tokens_in,
            tokens_out=out_cap,
        )
        limit = float(self._cfg.allocations[allocation])
        committed = self._spent[allocation] + self._reserved[allocation]
        if committed + est_cost > limit + 1e-12:
            action = self._cfg.on_exceed.get(allocation, "abort")
            reason = (
                f"{allocation} would spend ${committed + est_cost:.4f} "
                f"over limit ${limit:.4f} (est ${est_cost:.4f})"
            )
            note = DegradationNote(
                allocation=allocation,
                action=action,
                reason=reason,
                impact=_impact_for(action, allocation),
            )
            self.degradations.append(note)
            if action == "abort":
                raise BudgetExceeded(allocation, committed, limit, est_cost, detail=reason)
            if action == "degrade":
                raise BudgetDegrade(allocation, suggested_tier="small", detail=reason)
            raise BudgetSkip(allocation, action, detail=reason)

        self._reserved[allocation] += est_cost
        return BudgetReservation(
            allocation=allocation,
            reserved_usd=est_cost,
            tier=tier,
            estimated_tokens_in=estimated_tokens_in,
            estimated_tokens_out=out_cap,
        )

    def settle(
        self,
        reservation: BudgetReservation,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None = None,
    ) -> float:
        """Release reserved amount and charge actual (or recompute from usage)."""
        if reservation.settled:
            return float(reservation.actual_usd or 0.0)
        allocation = reservation.allocation
        self._require_allocation(allocation)
        actual = (
            float(cost_usd)
            if cost_usd is not None
            else price_usd_for_tier(
                self._llm,
                reservation.tier,
                tokens_in=prompt_tokens,
                tokens_out=completion_tokens,
            )
        )
        self._reserved[allocation] = max(0.0, self._reserved[allocation] - reservation.reserved_usd)
        self._spent[allocation] += actual
        reservation.settled = True
        reservation.actual_usd = actual
        return actual

    def release(self, reservation: BudgetReservation) -> None:
        """Drop reservation without charging (call failed before usage)."""
        if reservation.settled:
            return
        allocation = reservation.allocation
        self._require_allocation(allocation)
        self._reserved[allocation] = max(0.0, self._reserved[allocation] - reservation.reserved_usd)
        reservation.settled = True
        reservation.actual_usd = 0.0

    def _require_allocation(self, allocation: str) -> None:
        if allocation not in self._cfg.allocations:
            raise ConfigError(
                f"Unknown budget allocation {allocation!r}; known={sorted(self._cfg.allocations)}"
            )


def _impact_for(action: str, allocation: str) -> str:
    if action == "degrade":
        return f"{allocation}: reduce depth / fall back to cheaper path"
    if action == "l1_only":
        return f"{allocation}: rules-only monitoring; no LLM triage"
    if action == "skip":
        return f"{allocation}: skipped for today; retry tomorrow"
    return f"{allocation}: aborted"
