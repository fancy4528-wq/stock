"""Static dashboard over daily reports, shadow journals, and backtests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantagent.evaluation.agent import AgentScoreDay, AgentScorePoint, append_agent_score_day
from quantagent.evaluation.shadow.types import ShadowDayRecord, ShadowPortfolioId
from quantagent.reporting.dashboard import load_shadow_series, refresh_readout, write_dashboard


def _record(
    portfolio: ShadowPortfolioId,
    as_of: date,
    *,
    ret_cum: float,
    ret_1d: float = 0.0,
) -> str:
    return ShadowDayRecord(
        portfolio=portfolio,
        as_of=as_of,
        run_id="r",
        strategy_version="v1",
        nav=1_000_000,
        cash=0,
        ret_1d=ret_1d,
        ret_cum=ret_cum,
        max_drawdown=-0.01,
        n_positions=10,
    ).model_dump_json()


def test_last_row_for_a_day_wins(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    path = shadow / "shadow_baseline.jsonl"
    path.write_text(
        "\n".join(
            [
                _record("shadow_baseline", date(2026, 10, 29), ret_cum=0.01),
                _record("shadow_baseline", date(2026, 10, 30), ret_cum=0.02),
                _record("shadow_baseline", date(2026, 10, 30), ret_cum=0.015),
                "{",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    series, warnings = load_shadow_series(shadow)
    points = series["shadow_baseline"]
    assert [point.as_of for point in points] == [date(2026, 10, 29), date(2026, 10, 30)]
    assert points[-1].ret_cum == 0.015
    assert warnings


def test_dashboard_links_reports_and_ignores_synthetic_counts(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    reports = tmp_path / "reports"
    backtests = tmp_path / "backtests"
    reports.mkdir()
    backtests.mkdir()
    (shadow).mkdir()
    (shadow / "shadow_quant.jsonl").write_text(
        _record("shadow_quant", date(2026, 10, 30), ret_cum=0.0079, ret_1d=0.0079) + "\n",
        encoding="utf-8",
    )
    (reports / "2026-10-30.md").write_text(
        "# 测试日报\n\n## 一、市场概况\n\n池内上涨。\n",
        encoding="utf-8",
    )
    (reports / "notes.md").write_text("# 不是日报\n", encoding="utf-8")
    (backtests / "l2_equal_topn-csi300-5y.md").write_text(
        "# 回测测试\n\n总收益 −5.4%。\n",
        encoding="utf-8",
    )
    (backtests / "l2_equal_topn-synthetic.md").write_text(
        "# 回测测试\n\n合成。\n", encoding="utf-8"
    )
    (backtests / "README.md").write_text("# 说明\n", encoding="utf-8")
    append_agent_score_day(
        shadow,
        AgentScoreDay(
            as_of=date(2026, 10, 30),
            run_id="live",
            origin="live",
            points=[AgentScorePoint(symbol="600000.SH", score=0.6, confidence=0.7)],
        ),
    )
    append_agent_score_day(
        shadow,
        AgentScoreDay(
            as_of=date(2026, 10, 29),
            run_id="syn",
            origin="synthetic",
            points=[AgentScorePoint(symbol="600000.SH", score=0.2, confidence=0.4)],
        ),
    )
    agent_eval = tmp_path / "agent-ic.md"
    agent_eval.write_text("# Agent IC\n\n样本不足。\n", encoding="utf-8")

    out = tmp_path / "dash" / "index.html"
    write_dashboard(
        shadow_dir=shadow,
        reports_dir=reports,
        backtests_dir=backtests,
        out=out,
        agent_eval=agent_eval,
    )
    html = out.read_text(encoding="utf-8")
    assert "不构成投资建议" in html
    assert "shadow_quant · 量化" in html
    assert "+0.79%" in html
    assert "plotly" in html
    assert "cdn.plot.ly" in html
    assert "daily/2026-10-30.html" in html
    assert "backtests/l2_equal_topn-csi300-5y.html" in html
    assert "回测测试 (l2_equal_topn-csi300-5y)" in html
    assert "回测测试 (l2_equal_topn-synthetic)" in html
    assert "不是日报" not in html
    assert "live 1 天（1 个分数），synthetic 1 天。IC 与校准" in html
    assert "agent-ic.html" in html

    daily = (tmp_path / "dash" / "daily" / "2026-10-30.html").read_text(encoding="utf-8")
    assert "池内上涨" in daily
    assert "<h2>一、市场概况</h2>" in daily
    backtest = (tmp_path / "dash" / "backtests" / "l2_equal_topn-csi300-5y.html").read_text(
        encoding="utf-8"
    )
    assert "总收益" in backtest
    assert (tmp_path / "dash" / "backtests" / "README.html").exists() is False


def test_empty_dirs_still_render(tmp_path: Path) -> None:
    out = tmp_path / "dash" / "index.html"
    write_dashboard(
        shadow_dir=tmp_path / "missing-shadow",
        reports_dir=tmp_path / "missing-reports",
        backtests_dir=tmp_path / "missing-backtests",
        out=out,
        agent_eval=tmp_path / "missing-ic.md",
    )
    html = out.read_text(encoding="utf-8")
    assert "尚无 Shadow 记录" in html
    assert "尚无日报" in html
    assert "尚无回测" in html
    assert "IC 报告尚未生成" in html
    assert "live 0 天" in html


def test_refresh_readout_swallows_render_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**_kwargs: object) -> Path:
        raise RuntimeError("plot failed")

    monkeypatch.setattr("quantagent.reporting.dashboard.write_dashboard", _boom)
    assert (
        refresh_readout(reports_dir=tmp_path / "daily-reports", shadow_dir=tmp_path / "shadow")
        is None
    )
