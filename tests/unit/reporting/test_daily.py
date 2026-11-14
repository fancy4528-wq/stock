"""Daily markdown renderer tests."""

from __future__ import annotations

from datetime import date

from quantagent.agents.reporter import build_deterministic_report
from quantagent.agents.tools.market import RiskNote
from quantagent.reporting.daily import render_daily_report
from quantagent.reporting.pipeline import build_synthetic_bundle


def test_render_contains_required_sections() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    report = build_deterministic_report(bundle)
    md = render_daily_report(report, bundle)
    assert "A股市场日报" in md
    assert "## 二、重要事件" in md
    assert "Shadow Portfolio" in md
    assert "不构成投资建议" in md
    assert "买入建议" not in md
    assert report.run_id in md
    assert report.event_summary is not None


def test_render_puts_market_shock_under_overview() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    note = "市场冲击：因「中东军事冲突升级」（军事冲突），建议偏向防守；不改变仓位。"
    bundle = bundle.model_copy(update={"risk_notes": [RiskNote(text=note)]})
    report = build_deterministic_report(bundle)
    md = render_daily_report(report, bundle)
    overview = md.split("## 二、重要事件")[0]
    assert note in overview
    assert "不改变仓位" in overview
