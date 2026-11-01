"""Agent score IC and confidence calibration."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from quantagent.agents.schemas.views import RankedStock
from quantagent.evaluation.agent import (
    AgentScoreDay,
    AgentScorePoint,
    append_agent_score_day,
    check_calibration,
    confidence_bucket,
    evaluate_agent_scores,
    load_agent_score_days,
    points_from_ranking,
    write_agent_eval_report,
)
from quantagent.evaluation.agent.evaluate import AgentEvalError


def test_confidence_bucket_edges() -> None:
    assert confidence_bucket(0.0) == "0.0-0.5"
    assert confidence_bucket(0.499) == "0.0-0.5"
    assert confidence_bucket(0.5) == "0.5-0.7"
    assert confidence_bucket(0.7) == "0.7-0.85"
    assert confidence_bucket(0.85) == "0.85-1.0"
    assert confidence_bucket(1.0) == "0.85-1.0"


def test_points_keep_raw_score() -> None:
    points = points_from_ranking(
        [
            RankedStock(
                rank=1,
                symbol="600000.SH",
                name="浦发银行",
                sector_code="bank",
                score=0.8,
                confidence=0.4,
                action_hint="candidate",
                one_liner="n",
            )
        ]
    )
    assert points[0].score == pytest.approx(0.8)
    assert points[0].confidence == pytest.approx(0.4)


def test_journal_is_idempotent_per_day(tmp_path: Path) -> None:
    day = AgentScoreDay(
        as_of=date(2026, 10, 30),
        run_id="r1",
        points=[AgentScorePoint(symbol="A", score=0.7, confidence=0.6)],
    )
    assert append_agent_score_day(tmp_path, day) is True
    assert append_agent_score_day(tmp_path, day) is False
    assert (
        append_agent_score_day(
            tmp_path,
            AgentScoreDay(as_of=date(2026, 10, 30), run_id="r2", points=[]),
        )
        is False
    )
    loaded = load_agent_score_days(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].points[0].score == pytest.approx(0.7)
    assert load_agent_score_days(tmp_path / "missing") == []


def test_check_calibration_monotonic_and_flat() -> None:
    rising = check_calibration(
        [0.2, 0.3, 0.6, 0.65, 0.8, 0.82, 0.95, 0.99],
        [False, False, True, False, True, True, True, True],
    )
    assert rising.monotonic is True
    assert rising.slope is not None and rising.slope > 0
    assert rising.hit_rate_by_bucket["0.0-0.5"] == pytest.approx(0.0)
    assert rising.hit_rate_by_bucket["0.85-1.0"] == pytest.approx(1.0)

    flat = check_calibration([0.2, 0.95], [True, False])
    assert flat.monotonic is False
    assert flat.slope is not None and flat.slope < 0


def _panel(
    closes: dict[str, list[float]],
    *,
    limit_up: dict[str, list[bool]] | None = None,
) -> pl.DataFrame:
    start = date(2026, 1, 5)
    rows: list[dict[str, object]] = []
    for sym, series in closes.items():
        flags = (limit_up or {}).get(sym)
        for i, close in enumerate(series):
            row: dict[str, object] = {
                "symbol": sym,
                "trade_date": start + timedelta(days=i),
                "close": close,
            }
            if flags is not None:
                row["is_limit_up"] = flags[i]
                row["is_suspended"] = False
            rows.append(row)
    return pl.DataFrame(rows)


def test_score_ic_matches_return_rank() -> None:
    symbols = ["A", "B", "C", "D"]
    alphas = {"A": 0.0, "B": 0.01, "C": 0.02, "D": 0.03}
    scores = {"A": 0.2, "B": 0.4, "C": 0.7, "D": 0.9}
    n = 12
    closes = {sym: [100.0 * ((1.0 + alphas[sym]) ** t) for t in range(n)] for sym in symbols}
    start = date(2026, 1, 5)
    days = [
        AgentScoreDay(
            as_of=start + timedelta(days=i),
            run_id=f"r{i}",
            points=[
                AgentScorePoint(symbol=sym, score=scores[sym], confidence=0.4 + 0.1 * j)
                for j, sym in enumerate(symbols)
            ],
        )
        for i in range(6)
    ]
    result = evaluate_agent_scores(days, _panel(closes))
    assert result.score_ic_5d == pytest.approx(1.0)
    assert result.ranking_ic == pytest.approx(1.0)
    assert result.n_ic_days_5d == 6
    assert result.score_ic_20d is None
    assert result.calibration_monotonic is True
    assert "少于 20" in result.interpretation


def test_non_monotonic_confidence_is_called_out() -> None:
    closes = {
        "A": [100, 102, 104, 106, 108, 110],
        "B": [100, 102, 104, 106, 108, 110],
        "C": [100, 98, 96, 94, 92, 90],
        "D": [100, 98, 96, 94, 92, 90],
    }
    day = AgentScoreDay(
        as_of=date(2026, 1, 5),
        run_id="r",
        points=[
            AgentScorePoint(symbol="A", score=0.8, confidence=0.2),
            AgentScorePoint(symbol="B", score=0.8, confidence=0.3),
            AgentScorePoint(symbol="C", score=0.8, confidence=0.95),
            AgentScorePoint(symbol="D", score=0.8, confidence=0.96),
        ],
    )
    result = evaluate_agent_scores([day], _panel(closes))
    assert result.score_ic_5d is None
    assert result.calibration_monotonic is False
    assert result.confidence_calibration["0.0-0.5"] == pytest.approx(1.0)
    assert result.confidence_calibration["0.85-1.0"] == pytest.approx(0.0)
    assert "Fusion 应忽略该字段" in result.interpretation


def test_limit_up_entry_drops_label() -> None:
    closes = {
        "A": [100, 101, 102, 103, 104, 130],
        "B": [100, 101, 102, 103, 104, 120],
        "C": [100, 101, 102, 103, 104, 110],
        "D": [100, 101, 102, 103, 104, 105],
    }
    flags = {
        "A": [False, True, False, False, False, False],
        "B": [False] * 6,
        "C": [False] * 6,
        "D": [False] * 6,
    }
    day = AgentScoreDay(
        as_of=date(2026, 1, 5),
        run_id="r",
        points=[
            AgentScorePoint(symbol=sym, score=score, confidence=0.6)
            for sym, score in (("A", 0.9), ("B", 0.7), ("C", 0.4), ("D", 0.2))
        ],
    )
    result = evaluate_agent_scores([day], _panel(closes, limit_up=flags))
    assert result.n_labeled_5d == 3
    assert result.score_ic_5d == pytest.approx(1.0)


def test_synthetic_rows_are_excluded() -> None:
    closes = {
        "A": [100, 100, 100, 100, 100, 110],
        "B": [100, 100, 100, 100, 100, 120],
        "C": [100, 100, 100, 100, 100, 130],
    }
    day = AgentScoreDay(
        as_of=date(2026, 1, 5),
        run_id="syn",
        origin="synthetic",
        points=[
            AgentScorePoint(symbol="A", score=0.2, confidence=0.4),
            AgentScorePoint(symbol="B", score=0.5, confidence=0.6),
            AgentScorePoint(symbol="C", score=0.9, confidence=0.9),
        ],
    )
    with pytest.raises(AgentEvalError, match="no live"):
        evaluate_agent_scores([day], _panel(closes))


def test_missing_price_column_raises() -> None:
    day = AgentScoreDay(
        as_of=date(2026, 1, 5),
        run_id="r",
        points=[AgentScorePoint(symbol="A", score=0.5, confidence=0.5)],
    )
    with pytest.raises(AgentEvalError):
        evaluate_agent_scores([day], pl.DataFrame({"symbol": ["A"]}))


def test_report_renders_measured_ic(tmp_path: Path) -> None:
    closes = {
        sym: [100.0 * ((1.0 + alpha) ** t) for t in range(8)]
        for sym, alpha in (("A", 0.0), ("B", 0.01), ("C", 0.02))
    }
    day = AgentScoreDay(
        as_of=date(2026, 1, 5),
        run_id="r",
        points=[
            AgentScorePoint(symbol="A", score=0.2, confidence=0.4),
            AgentScorePoint(symbol="B", score=0.5, confidence=0.6),
            AgentScorePoint(symbol="C", score=0.9, confidence=0.9),
        ],
    )
    result = evaluate_agent_scores([day], _panel(closes))
    path = write_agent_eval_report(result, tmp_path / "agent-ic.md")
    text = path.read_text(encoding="utf-8")
    assert "score IC 5d" in text
    assert "+1.0000" in text
