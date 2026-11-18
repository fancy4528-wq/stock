"""Decision-context journal and condition accuracy."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from quantagent.agents.base import Evidence
from quantagent.agents.fixtures import sample_research_facts
from quantagent.agents.schemas.views import (
    AllocationStance,
    InputsSummary,
    MarketBrief,
    RankedSector,
)
from quantagent.evaluation.agent.types import AgentScoreDay, AgentScorePoint
from quantagent.evaluation.decisions import (
    DecisionContextDay,
    append_decision_context_day,
    condition_accuracy,
    context_from_research,
    event_tags_from,
    load_decision_context_days,
    synthetic_context,
    volatility_from_index_return,
)
from quantagent.evaluation.review import build_monthly_review, render_monthly_review


def _brief(*, as_of: date, regime: str, regime_note: str) -> MarketBrief:
    return MarketBrief(
        as_of=as_of,
        run_id="r",
        market_summary="summary",
        regime=regime,  # type: ignore[arg-type]
        regime_note=regime_note,
        sector_ranking=[
            RankedSector(
                rank=1,
                sector_code="801010",
                sector_name="农林牧渔",
                sector_type="industry",
                score=0.6,
                confidence=0.5,
                one_liner="test",
            )
        ],
        stock_ranking=[],
        allocation_stance=AllocationStance(
            equity_stance="moderate",
            rationale="test",
        ),
        disagreements=[],
        key_uncertainties=["u"],
        watchlist=[],
        inputs_summary=InputsSummary(data_as_of=as_of, sector_count=1, stock_count=0),
        evidence=[
            Evidence(
                evidence_id="e1",
                kind="news",
                ref_id="r1",
                excerpt="x",
                as_of=as_of,
            )
        ],
    )


def test_volatility_and_event_tags() -> None:
    assert volatility_from_index_return(0.02) == "high"
    assert volatility_from_index_return(-0.02) == "high"
    assert volatility_from_index_return(0.0) == "low"
    assert volatility_from_index_return(0.01) == "normal"
    assert event_tags_from(regime_drivers=["市场冲击[战争]：标题"], news_count=3) == [
        "market_shock"
    ]
    assert event_tags_from(regime_drivers=["平稳"], news_count=12) == ["high_news"]
    assert event_tags_from(regime_drivers=[], news_count=1) == []


def test_context_from_research_records_shock_and_vol() -> None:
    as_of = date(2026, 11, 17)
    facts = sample_research_facts().model_copy(
        update={"as_of": as_of, "index_return_1d": -0.02, "news_count": 15}
    )
    brief = _brief(
        as_of=as_of,
        regime="risk_off",
        regime_note="市场冲击[战争]：外盘大跌；指数下跌",
    )
    day = context_from_research(
        as_of=as_of, run_id="20261117-cn-daily", brief=brief, facts=facts
    )
    assert day.market_regime == "risk_off"
    assert day.volatility == "high"
    assert day.event_tags == ["market_shock", "high_news"]
    assert day.index_return_1d == -0.02


def test_decision_context_journal_idempotent(tmp_path: Path) -> None:
    day = synthetic_context(as_of=date(2026, 11, 17), run_id="r")
    assert append_decision_context_day(tmp_path, day) is True
    assert append_decision_context_day(tmp_path, day) is False
    loaded = load_decision_context_days(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].market_regime == "neutral"


def test_condition_accuracy_buckets_hits(tmp_path: Path) -> None:
    as_of = date(2026, 10, 20)
    contexts = [
        DecisionContextDay(
            as_of=as_of,
            run_id="r",
            market_regime="risk_on",
            volatility="high",
            event_tags=["market_shock"],
        )
    ]
    scores = [
        AgentScoreDay(
            as_of=as_of,
            run_id="r",
            points=[
                AgentScorePoint(symbol="AAA", score=0.8, confidence=0.7),
                AgentScorePoint(symbol="BBB", score=0.2, confidence=0.4),
                AgentScorePoint(symbol="CCC", score=0.9, confidence=0.8),
            ],
        )
    ]
    # Build 6 trading days so fwd_ret_5d resolves.
    rows: list[dict[str, object]] = []
    for i in range(6):
        d = as_of + timedelta(days=i)
        rows.extend(
            [
                {"symbol": "AAA", "trade_date": d, "close": 10.0 + i},
                {"symbol": "BBB", "trade_date": d, "close": 10.0 - 0.2 * i},
                {"symbol": "CCC", "trade_date": d, "close": 10.0 + 0.5 * i},
            ]
        )
    prices = pl.DataFrame(rows)
    rows_out, note = condition_accuracy(
        contexts,
        scores,
        prices,
        start=date(2026, 10, 1),
        end=date(2026, 10, 31),
    )
    by_cond = {r.condition: r for r in rows_out}
    assert "regime:risk_on" in by_cond
    assert "vol:high" in by_cond
    assert "event:market_shock" in by_cond
    assert by_cond["regime:risk_on"].accuracy_5d is not None
    assert "命中样本" in note


def test_monthly_review_reads_decision_context(tmp_path: Path) -> None:
    as_of = date(2026, 10, 30)
    append_decision_context_day(
        tmp_path,
        DecisionContextDay(
            as_of=as_of,
            run_id="r",
            market_regime="transition",
            volatility="low",
            event_tags=[],
        ),
    )
    review = build_monthly_review(month="2026-10", shadow_dir=tmp_path, cost_log_text=None)
    assert any(row.condition == "regime:transition" for row in review.conditions)
    assert any(row.condition == "vol:low" for row in review.conditions)
    text = render_monthly_review(review)
    assert "regime:transition" in text
    assert "未提供行情" in text
