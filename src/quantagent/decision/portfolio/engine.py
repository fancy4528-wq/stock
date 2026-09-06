"""Equal-weight Top-N portfolio construction (MVP)."""

from __future__ import annotations

from collections.abc import Mapping

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.decision.portfolio.config import PortfolioConfig, load_portfolio_config
from quantagent.decision.portfolio.lots import round_weights_to_lots
from quantagent.decision.portfolio.types import CandidateMeta, TargetPortfolio


def _exclusion_reason(meta: CandidateMeta | None) -> str | None:
    if meta is None:
        return None
    if meta.is_suspended:
        return "is_suspended"
    if meta.is_st:
        return "is_st"
    if meta.in_blacklist:
        return "in_blacklist"
    return None


def build_equal_weight_portfolio(
    scores: Mapping[str, float | None],
    *,
    meta: dict[str, CandidateMeta] | None = None,
    cfg: PortfolioConfig | None = None,
    market: MarketConfig | None = None,
    total_value: float | None = None,
    apply_lots: bool = False,
) -> TargetPortfolio:
    """Select Top-N by score, assign equal weights, optionally lot-round.

    Scores below ``min_score`` or with null score are excluded. Prefer empty
    portfolio over forcing low-score names in.
    """
    cfg = cfg or load_portfolio_config("CN")
    market = market or load_market_config("CN")
    meta = meta or {}

    excluded: dict[str, str] = {}
    eligible: list[tuple[str, float]] = []
    for symbol, score in scores.items():
        if score is None:
            excluded[symbol] = "score_null"
            continue
        if score < cfg.selection.min_score:
            excluded[symbol] = "below_min_score"
            continue
        reason = _exclusion_reason(meta.get(symbol))
        if reason is not None:
            excluded[symbol] = reason
            continue
        eligible.append((symbol, float(score)))

    eligible.sort(key=lambda x: x[1], reverse=True)
    selected = [s for s, _ in eligible[: cfg.selection.top_n]]
    if not selected:
        return TargetPortfolio(
            weights={},
            cash_weight=1.0,
            selected=[],
            excluded=excluded,
            method=cfg.weighting.method,
        )

    raw_w = cfg.weighting.max_gross_exposure / len(selected)
    weights = {s: raw_w for s in selected}

    cash_weight = 1.0 - sum(weights.values())
    if apply_lots and total_value is not None and total_value > 0:
        prices: dict[str, float] = {}
        boards: dict[str, str] = {}
        for s in selected:
            m = meta.get(s)
            if m is None or m.price is None or m.price <= 0:
                continue
            prices[s] = float(m.price)
            boards[s] = m.board
        if prices:
            weights, cash_weight = round_weights_to_lots(
                weights,
                prices=prices,
                total_value=total_value,
                market=market,
                boards=boards,
            )
            selected = [s for s in selected if s in weights]

    return TargetPortfolio(
        weights=weights,
        cash_weight=cash_weight,
        selected=selected,
        excluded=excluded,
        method=cfg.weighting.method,
    )
