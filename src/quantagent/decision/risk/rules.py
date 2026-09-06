"""MVP hard risk rules. Each rule returns updated weights + violations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from quantagent.core.market import MarketConfig
from quantagent.decision.risk.config import RiskConfig
from quantagent.decision.risk.types import (
    PortfolioState,
    RiskViolation,
    SecurityContext,
)


@dataclass
class RuleOutcome:
    weights: dict[str, float]
    violations: list[RiskViolation] = field(default_factory=list)
    action: str = "continue"  # continue | reject_all


class RiskRule(Protocol):
    code: str

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome: ...


class ConsistencySumRule:
    code = "CON_001"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        total = sum(weights.values())
        if total > 1.0 + 1e-9:
            return RuleOutcome(
                weights=weights,
                violations=[
                    RiskViolation(
                        rule_code=self.code,
                        detail=f"weight sum {total:.4f} > 1.0",
                        action="reject_all",
                    )
                ],
                action="reject_all",
            )
        return RuleOutcome(weights=weights)


class NoShortRule:
    code = "POS_010"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        if market.short_selling_allowed:
            return RuleOutcome(weights=weights)
        bad = [s for s, w in weights.items() if w < -1e-12]
        if bad:
            return RuleOutcome(
                weights=weights,
                violations=[
                    RiskViolation(
                        rule_code=self.code,
                        detail=f"negative weights not allowed: {bad}",
                        action="reject_all",
                    )
                ],
                action="reject_all",
            )
        return RuleOutcome(weights=weights)


class ExcludeSTRule:
    code = "EXC_001"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        if not cfg.exclusion.reject_st:
            return RuleOutcome(weights=weights)
        out = dict(weights)
        violations: list[RiskViolation] = []
        for symbol in list(out):
            ctx = context.get(symbol)
            if ctx is not None and ctx.is_st and out[symbol] > 0:
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail="ST / *ST excluded",
                        symbol=symbol,
                        action="reject",
                    )
                )
                del out[symbol]
        return RuleOutcome(weights=out, violations=violations)


class SuspendedRule:
    code = "EXE_001"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        if not cfg.exclusion.reject_suspended:
            return RuleOutcome(weights=weights)
        out = dict(weights)
        violations: list[RiskViolation] = []
        for symbol in list(out):
            ctx = context.get(symbol)
            current = state.weight(symbol)
            # Reject increases / new buys while suspended
            if ctx is not None and ctx.is_suspended and out[symbol] > current + 1e-12:
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail="suspended cannot trade",
                        symbol=symbol,
                        action="reject",
                    )
                )
                del out[symbol]
        return RuleOutcome(weights=out, violations=violations)


class LimitUpBuyRule:
    code = "EXE_002"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        if not cfg.exclusion.reject_limit_up_buy:
            return RuleOutcome(weights=weights)
        out = dict(weights)
        violations: list[RiskViolation] = []
        for symbol in list(out):
            ctx = context.get(symbol)
            current = state.weight(symbol)
            if ctx is not None and ctx.is_limit_up and out[symbol] > current + 1e-12:
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail="limit-up cannot buy",
                        symbol=symbol,
                        action="reject",
                    )
                )
                # Keep existing weight if any; else drop
                if current > 0:
                    out[symbol] = current
                else:
                    del out[symbol]
        return RuleOutcome(weights=out, violations=violations)


class LiquidityRule:
    code = "LIQ_001"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        out = dict(weights)
        violations: list[RiskViolation] = []
        floor = cfg.liquidity.min_avg_amount_20d
        for symbol in list(out):
            if out[symbol] <= 0:
                continue
            ctx = context.get(symbol)
            # Fail closed: missing liquidity data → reject
            if ctx is None or ctx.avg_amount_20d is None or ctx.avg_amount_20d < floor:
                amt = None if ctx is None else ctx.avg_amount_20d
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail=f"avg_amount_20d={amt} < {floor}",
                        symbol=symbol,
                        action="reject",
                    )
                )
                del out[symbol]
        return RuleOutcome(weights=out, violations=violations)


class SingleWeightCapRule:
    code = "POS_001"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        cap = cfg.position.max_single_weight
        out = dict(weights)
        violations: list[RiskViolation] = []
        for symbol, w in list(out.items()):
            if w > cap + 1e-12:
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail=f"weight {w:.4f} clipped to {cap:.4f}",
                        symbol=symbol,
                        action="clip",
                    )
                )
                out[symbol] = cap
        return RuleOutcome(weights=out, violations=violations)


class IndustryCapRule:
    code = "POS_002"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        cap = cfg.position.max_industry_weight
        by_ind: dict[str, list[str]] = {}
        for symbol, w in weights.items():
            if w <= 0:
                continue
            ctx = context.get(symbol)
            ind = (ctx.industry if ctx is not None else None) or "UNKNOWN"
            by_ind.setdefault(ind, []).append(symbol)

        out = dict(weights)
        violations: list[RiskViolation] = []
        for ind, syms in by_ind.items():
            total = sum(out[s] for s in syms)
            if total <= cap + 1e-12:
                continue
            scale = cap / total
            for s in syms:
                out[s] *= scale
            violations.append(
                RiskViolation(
                    rule_code=self.code,
                    detail=f"industry {ind} weight {total:.4f} scaled to {cap:.4f}",
                    action="clip",
                )
            )
        return RuleOutcome(weights=out, violations=violations)


class GrossExposureRule:
    code = "POS_007"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        cap = cfg.position.max_gross_exposure
        total = sum(max(0.0, w) for w in weights.values())
        if total <= cap + 1e-12:
            return RuleOutcome(weights=weights)
        scale = cap / total if total > 0 else 0.0
        out = {s: w * scale for s, w in weights.items()}
        return RuleOutcome(
            weights=out,
            violations=[
                RiskViolation(
                    rule_code=self.code,
                    detail=f"gross {total:.4f} scaled to {cap:.4f}",
                    action="scale",
                )
            ],
        )


class MinCashRule:
    code = "POS_008"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        min_cash = cfg.position.min_cash
        max_gross = 1.0 - min_cash
        total = sum(max(0.0, w) for w in weights.values())
        if total <= max_gross + 1e-12:
            return RuleOutcome(weights=weights)
        scale = max_gross / total if total > 0 else 0.0
        out = {s: w * scale for s, w in weights.items()}
        return RuleOutcome(
            weights=out,
            violations=[
                RiskViolation(
                    rule_code=self.code,
                    detail=f"cash {1 - total:.4f} below {min_cash:.4f}; scaled",
                    action="scale",
                )
            ],
        )


class LotRoundRule:
    """EXE_005: floor buy notionals to lot sizes when prices available."""

    code = "EXE_005"

    def apply(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        cfg: RiskConfig,
        market: MarketConfig,
        as_of: date,
        context: dict[str, SecurityContext],
    ) -> RuleOutcome:
        if state.total_value <= 0:
            return RuleOutcome(weights=weights)
        from quantagent.decision.portfolio.lots import round_weights_to_lots

        prices: dict[str, float] = {}
        boards: dict[str, str] = {}
        for symbol, w in weights.items():
            if w <= 0:
                continue
            ctx = context.get(symbol)
            if ctx is None or ctx.price is None or ctx.price <= 0:
                continue
            prices[symbol] = float(ctx.price)
            boards[symbol] = ctx.board
        if not prices:
            return RuleOutcome(weights=weights)

        rounded, _cash = round_weights_to_lots(
            {s: weights[s] for s in prices},
            prices=prices,
            total_value=state.total_value,
            market=market,
            boards=boards,
        )
        out = dict(weights)
        violations: list[RiskViolation] = []
        for symbol in list(out):
            if symbol not in prices:
                continue
            before = out[symbol]
            after = rounded.get(symbol, 0.0)
            if after <= 0:
                del out[symbol]
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail="lot floor removed position",
                        symbol=symbol,
                        action="clip",
                    )
                )
            elif abs(after - before) > 1e-12:
                out[symbol] = after
                violations.append(
                    RiskViolation(
                        rule_code=self.code,
                        detail=f"lot floor {before:.4f} -> {after:.4f}",
                        symbol=symbol,
                        action="clip",
                    )
                )
        return RuleOutcome(weights=out, violations=violations)


def default_mvp_rules() -> list[RiskRule]:
    """Fixed order per docs/09-portfolio-risk.md §4.4 (MVP subset)."""
    return [
        ConsistencySumRule(),
        NoShortRule(),
        ExcludeSTRule(),
        SuspendedRule(),
        LimitUpBuyRule(),
        LiquidityRule(),
        SingleWeightCapRule(),
        IndustryCapRule(),
        GrossExposureRule(),
        MinCashRule(),
        LotRoundRule(),
    ]
