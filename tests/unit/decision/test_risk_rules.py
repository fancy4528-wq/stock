"""Unit tests for MVP hard risk rules (W7)."""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.decision.risk import (
    PortfolioState,
    RiskDecision,
    RiskEngine,
    SecurityContext,
)
from quantagent.decision.risk.config import RiskConfig
from quantagent.decision.risk.rules import (
    ConsistencySumRule,
    ExcludeSTRule,
    GrossExposureRule,
    IndustryCapRule,
    LimitUpBuyRule,
    LiquidityRule,
    LotRoundRule,
    MinCashRule,
    NoShortRule,
    SingleWeightCapRule,
    SuspendedRule,
)

AS_OF = date(2024, 6, 3)


def _state(**kwargs: object) -> PortfolioState:
    base: dict[str, object] = {
        "as_of": AS_OF,
        "cash": 100_000.0,
        "total_value": 1_000_000.0,
        "peak_value": 1_000_000.0,
    }
    base.update(kwargs)
    return PortfolioState.model_validate(base)


def _engine() -> RiskEngine:
    return RiskEngine()


def test_con_001_rejects_overweight_sum() -> None:
    engine = RiskEngine(rules=[ConsistencySumRule()])
    result = engine.check({"A": 0.6, "B": 0.6}, _state(), as_of=AS_OF)
    assert result.decision == RiskDecision.REJECT
    assert any(v.rule_code == "CON_001" for v in result.violations)


def test_pos_010_rejects_negative() -> None:
    engine = RiskEngine(rules=[NoShortRule()])
    result = engine.check({"A": -0.1}, _state(), as_of=AS_OF)
    assert result.decision == RiskDecision.REJECT
    assert any(v.rule_code == "POS_010" for v in result.violations)


def test_exc_001_rejects_st() -> None:
    engine = RiskEngine(rules=[ExcludeSTRule()])
    ctx = {"A": SecurityContext(symbol="A", is_st=True)}
    result = engine.check({"A": 0.1}, _state(), as_of=AS_OF, context=ctx)
    assert result.decision == RiskDecision.MODIFY
    assert "A" not in result.final_target
    assert any(v.rule_code == "EXC_001" for v in result.violations)


def test_exe_001_rejects_suspended_buy() -> None:
    engine = RiskEngine(rules=[SuspendedRule()])
    ctx = {"A": SecurityContext(symbol="A", is_suspended=True)}
    result = engine.check({"A": 0.1}, _state(), as_of=AS_OF, context=ctx)
    assert "A" not in result.final_target
    assert any(v.rule_code == "EXE_001" for v in result.violations)


def test_exe_002_rejects_limit_up_buy() -> None:
    engine = RiskEngine(rules=[LimitUpBuyRule()])
    ctx = {"A": SecurityContext(symbol="A", is_limit_up=True)}
    result = engine.check({"A": 0.1}, _state(), as_of=AS_OF, context=ctx)
    assert "A" not in result.final_target
    assert any(v.rule_code == "EXE_002" for v in result.violations)


def test_liq_001_rejects_illiquid() -> None:
    engine = RiskEngine(rules=[LiquidityRule()])
    ctx = {"A": SecurityContext(symbol="A", avg_amount_20d=1_000.0)}
    result = engine.check({"A": 0.1}, _state(), as_of=AS_OF, context=ctx)
    assert "A" not in result.final_target
    assert any(v.rule_code == "LIQ_001" for v in result.violations)


def test_liq_001_fail_closed_missing_amount() -> None:
    engine = RiskEngine(rules=[LiquidityRule()])
    result = engine.check({"A": 0.1}, _state(), as_of=AS_OF, context={})
    assert "A" not in result.final_target


def test_pos_001_clips_single_weight() -> None:
    engine = RiskEngine(rules=[SingleWeightCapRule()])
    result = engine.check({"A": 0.25}, _state(), as_of=AS_OF)
    assert result.final_target["A"] == pytest.approx(0.10)
    assert any(v.rule_code == "POS_001" for v in result.violations)


def test_pos_002_clips_industry() -> None:
    engine = RiskEngine(rules=[IndustryCapRule()])
    ctx = {
        "A": SecurityContext(symbol="A", industry="电子", avg_amount_20d=1e8),
        "B": SecurityContext(symbol="B", industry="电子", avg_amount_20d=1e8),
        "C": SecurityContext(symbol="C", industry="电子", avg_amount_20d=1e8),
    }
    target = {"A": 0.12, "B": 0.12, "C": 0.12}  # industry 0.36 > 0.25
    result = engine.check(target, _state(), as_of=AS_OF, context=ctx)
    assert sum(result.final_target.values()) == pytest.approx(0.25)
    assert any(v.rule_code == "POS_002" for v in result.violations)


def test_pos_007_scales_gross() -> None:
    engine = RiskEngine(rules=[GrossExposureRule()])
    result = engine.check({"A": 0.5, "B": 0.5}, _state(), as_of=AS_OF)
    assert sum(result.final_target.values()) == pytest.approx(0.90)


def test_pos_008_enforces_min_cash() -> None:
    cfg = RiskConfig()
    cfg.position.max_gross_exposure = 1.0  # so only POS_008 bites
    engine = RiskEngine(cfg=cfg, rules=[MinCashRule()])
    result = engine.check({"A": 0.95}, _state(), as_of=AS_OF)
    assert sum(result.final_target.values()) == pytest.approx(0.90)


def test_exe_005_lot_floor() -> None:
    engine = RiskEngine(rules=[LotRoundRule()])
    ctx = {"A": SecurityContext(symbol="A", price=33.0, board="main", avg_amount_20d=1e8)}
    # 0.05 * 1e6 / 33 ≈ 1515 → 1500 lots → weight 0.0495
    result = engine.check({"A": 0.05}, _state(total_value=1_000_000.0), as_of=AS_OF, context=ctx)
    assert result.final_target["A"] == pytest.approx(1500 * 33 / 1_000_000)
    assert any(v.rule_code == "EXE_005" for v in result.violations)


def test_full_engine_approve_clean_target() -> None:
    engine = _engine()
    symbols = [f"S{i}" for i in range(10)]
    target = {s: 0.08 for s in symbols}  # sum 0.80
    ctx = {
        s: SecurityContext(
            symbol=s,
            industry=f"I{i % 5}",
            avg_amount_20d=1e8,
            price=10.0,
            board="main",
        )
        for i, s in enumerate(symbols)
    }
    result = engine.check(target, _state(total_value=1_000_000.0), as_of=AS_OF, context=ctx)
    assert result.decision in {RiskDecision.APPROVE, RiskDecision.MODIFY}
    assert result.final_target
    assert result.config_hash
