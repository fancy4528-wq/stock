"""RiskEngine: deterministic hard checks with fail-closed behavior."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.decision.risk.config import RiskConfig, load_risk_config
from quantagent.decision.risk.rules import RiskRule, default_mvp_rules
from quantagent.decision.risk.types import (
    PortfolioState,
    RiskDecision,
    RiskResult,
    RiskViolation,
    SecurityContext,
)


def _hash_config(cfg: RiskConfig, market: MarketConfig) -> str:
    payload = {
        "risk": cfg.model_dump(),
        "market": market.market,
        "same_day_sell_allowed": market.same_day_sell_allowed,
        "min_lot_buy": market.min_lot_buy,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


class RiskEngine:
    """No override / force / bypass parameters — by design."""

    def __init__(
        self,
        cfg: RiskConfig | None = None,
        market: MarketConfig | None = None,
        *,
        rules: list[RiskRule] | None = None,
    ) -> None:
        self._cfg = cfg or load_risk_config("CN")
        self._market = market or load_market_config("CN")
        self._rules = rules if rules is not None else default_mvp_rules()
        self._config_hash = _hash_config(self._cfg, self._market)

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def check(
        self,
        target: dict[str, float],
        state: PortfolioState,
        *,
        as_of: date,
        context: dict[str, SecurityContext] | None = None,
    ) -> RiskResult:
        """Validate / clip target weights. Exceptions → REJECT."""
        context = context or {}
        violations: list[RiskViolation] = []
        weights = dict(target)

        try:
            for rule in self._rules:
                outcome = rule.apply(weights, state, self._cfg, self._market, as_of, context)
                violations.extend(outcome.violations)
                if outcome.action == "reject_all":
                    return RiskResult(
                        decision=RiskDecision.REJECT,
                        original_target=target,
                        final_target={},
                        violations=violations,
                        config_hash=self._config_hash,
                    )
                weights = outcome.weights
        except Exception as exc:  # noqa: BLE001 — fail closed
            return RiskResult(
                decision=RiskDecision.REJECT,
                original_target=target,
                final_target={},
                violations=[
                    *violations,
                    RiskViolation(
                        rule_code="ENGINE_ERROR",
                        detail=str(exc),
                        action="reject_all",
                    ),
                ],
                config_hash=self._config_hash,
            )

        # Drop zero weights for comparison cleanliness
        final = {s: w for s, w in weights.items() if abs(w) > 1e-12}
        if final == {s: w for s, w in target.items() if abs(w) > 1e-12}:
            decision = RiskDecision.APPROVE
        else:
            decision = RiskDecision.MODIFY
        return RiskResult(
            decision=decision,
            original_target=target,
            final_target=final,
            violations=violations,
            config_hash=self._config_hash,
        )
