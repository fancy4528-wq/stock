"""Monthly self-evaluation sections."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from quantagent.evaluation.review import (
    assess_factor,
    build_monthly_review,
    render_monthly_review,
    write_monthly_review,
)
from quantagent.evaluation.review.costs import summarize_cost_log
from quantagent.evaluation.review.shadows import load_shadow_month
from quantagent.evaluation.review.types import ConditionAccuracy
from quantagent.evaluation.signals import SignalScoreDay


def _shadow_line(
    portfolio: str,
    as_of: str,
    *,
    nav: float,
    ret_1d: float,
    ret_cum: float,
) -> str:
    return json.dumps(
        {
            "portfolio": portfolio,
            "as_of": as_of,
            "run_id": "r",
            "strategy_version": "gate3-l2-equal-v1",
            "nav": nav,
            "cash": 0.0,
            "ret_1d": ret_1d,
            "ret_cum": ret_cum,
            "max_drawdown": -0.01,
            "n_positions": 2,
            "unfilled": [{"reason": "limit_up"}] if as_of.endswith("30") else [],
        }
    )


def test_factor_decay_rules() -> None:
    healthy = assess_factor("ep_ttm", hist_ic=0.04, recent_ic=0.03)
    assert healthy.status == "healthy"
    assert healthy.decay_ratio == 0.75
    weak = assess_factor("ep_ttm", hist_ic=0.04, recent_ic=0.01)
    assert weak.status == "weakening"
    flipped = assess_factor("ep_ttm", hist_ic=0.04, recent_ic=-0.01)
    assert flipped.status == "weakening"
    unknown = assess_factor("ep_ttm", hist_ic=0.04, recent_ic=None)
    assert unknown.status == "unknown"
    assert unknown.decay_ratio is None


def test_cost_log_uses_run_id_date() -> None:
    october = (
        "| 2026-11-01T02:00:00+00:00 | 20261030-cn-daily | reporter | "
        "daily_research | m | live | 1 | 2 | 0.2500 |"
    )
    september = (
        "| 2026-10-15T02:00:00+00:00 | 20260930-cn-daily | reporter | "
        "monitoring | m | live | 1 | 2 | 1.0000 |"
    )
    text = "\n".join(
        [
            "| UTC | run_id | agent | allocation | model | mode | prompt | completion | USD |",
            "|---|---|---|---|---|---|---:|---:|---:|",
            october,
            september,
            "| not a row |",
        ]
    )
    summary = summarize_cost_log(text, start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert summary.n_rows == 1
    assert summary.usd == 0.25
    assert summary.by_allocation == {"daily_research": 0.25}


def test_shadow_month_compounds_and_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "shadow_baseline.jsonl"
    path.write_text(
        "\n".join(
            [
                _shadow_line("shadow_baseline", "2026-10-29", nav=110.0, ret_1d=0.10, ret_cum=0.10),
                "{not json",
                _shadow_line(
                    "shadow_baseline", "2026-10-30", nav=104.5, ret_1d=-0.05, ret_cum=0.045
                ),
                _shadow_line("shadow_baseline", "2026-09-30", nav=100.0, ret_1d=0.0, ret_cum=0.0),
            ]
        ),
        encoding="utf-8",
    )
    rows, warnings, seen = load_shadow_month(
        tmp_path, start=date(2026, 10, 1), end=date(2026, 10, 31)
    )
    baseline = next(row for row in rows if row.portfolio == "shadow_baseline")
    assert baseline.n_days == 2
    assert baseline.ret_month == 1.1 * 0.95 - 1
    assert baseline.max_drawdown == (104.5 / 110.0 - 1.0)
    assert baseline.n_unfilled == 1
    assert warnings
    assert "shadow_baseline" in seen
    assert next(row for row in rows if row.portfolio == "shadow_quant").n_days == 0


def test_monthly_review_keeps_seven_sections_and_weights(tmp_path: Path) -> None:
    symbols = [f"S{i}" for i in range(6)]
    scores = {sym: float(i) for i, sym in enumerate(symbols)}
    review = build_monthly_review(
        month="2026-10",
        shadow_dir=tmp_path,
        cost_log_text=None,
        signal_days=[
            SignalScoreDay(
                as_of=date(2026, 10, 30),
                run_id="r",
                signals={"factor": scores, "quant": scores},
            )
        ],
        recent_factor_ic={"ep_ttm": 0.01},
        conditions=[ConditionAccuracy(condition="high_vol", n=4, accuracy_5d=0.5)],
    )
    text = render_monthly_review(review)
    for heading in (
        "## 1. 整体表现",
        "## 2. 信号有效性",
        "## 3. 因子健康度",
        "## 4. Agent 质量",
        "## 5. 分条件准确率",
        "## 6. 失效告警",
        "## 7. 成本分析",
    ):
        assert heading in text
    assert review.signals.weights_changed is False
    assert "本次是否修改 Fusion 权重：否" in text
    assert any(row.factor == "ep_ttm" and row.status == "weakening" for row in review.factors)
    assert "high_vol" in text
    assert "未提供成本日志" in text
    path = write_monthly_review(review, tmp_path / "2026-10.md")
    assert path.is_file()
