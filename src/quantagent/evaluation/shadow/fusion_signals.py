"""Build fused Top-N targets; optionally clip via RiskEngine."""

from __future__ import annotations

from datetime import date

from quantagent.decision.fusion import FusionConfig, SignalFusion
from quantagent.decision.risk import RiskEngine, SecurityContext
from quantagent.decision.risk.types import PortfolioState
from quantagent.execution.broker.simulated import PriceBar


def fuse_quant_agent_scores(
    quant_scores: dict[str, float],
    agent_scores: dict[str, float],
    *,
    cfg: FusionConfig | None = None,
) -> dict[str, float]:
    """Map quant→``quant``, agent→``stock``; return final fused scores."""
    signals: dict[str, dict[str, float]] = {}
    if quant_scores:
        signals["quant"] = quant_scores
    if agent_scores:
        signals["stock"] = agent_scores
    if not signals:
        return {}
    fused = SignalFusion().fuse(signals, cfg or FusionConfig())
    return {sym: fs.final_score for sym, fs in fused.items()}


def security_context_from_bars(
    bars: list[PriceBar],
    *,
    symbols: list[str] | None = None,
) -> dict[str, SecurityContext]:
    """Build risk context from the session bars (day amount ≈ liquidity proxy)."""
    want = set(symbols) if symbols is not None else None
    out: dict[str, SecurityContext] = {}
    for bar in bars:
        if want is not None and bar.symbol not in want:
            continue
        amount = bar.amount if bar.amount > 0 else bar.volume * bar.close
        out[bar.symbol] = SecurityContext(
            symbol=bar.symbol,
            is_suspended=bar.is_suspended,
            is_limit_up=bar.is_limit_up,
            is_limit_down=bar.is_limit_down,
            price=bar.close,
            avg_amount_20d=amount,
            board="main",
        )
    return out


def top_n_symbols(scores: dict[str, float], n: int) -> list[str]:
    if n <= 0 or not scores:
        return []
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [s for s, _ in ranked[:n]]


def apply_risk_filter(
    symbols: list[str],
    *,
    bars: list[PriceBar],
    as_of: date,
    total_value: float,
    cash: float = 0.0,
    risk: RiskEngine | None = None,
) -> tuple[list[str], list[str]]:
    """Equal-weight ``symbols``, run RiskEngine, return surviving names + notes."""
    if not symbols:
        return [], []
    n = len(symbols)
    target = {s: 1.0 / n for s in symbols}
    ctx = security_context_from_bars(bars, symbols=symbols)
    state = PortfolioState(
        as_of=as_of,
        cash=cash,
        total_value=total_value if total_value > 0 else 1.0,
    )
    engine = risk or RiskEngine()
    result = engine.check(target, state, as_of=as_of, context=ctx)
    notes: list[str] = [f"risk:{result.decision.value}"]
    if result.decision.value == "reject":
        return [], notes + ["risk_reject_all"]
    kept = [s for s in symbols if s in result.final_target]
    dropped = len(symbols) - len(kept)
    if dropped:
        notes.append(f"risk_dropped:{dropped}")
    codes = sorted({v.rule_code for v in result.violations})
    if codes:
        notes.append("risk_rules:" + ",".join(codes[:8]))
    return kept, notes
