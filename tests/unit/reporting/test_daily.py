"""Daily markdown renderer tests."""

from __future__ import annotations

from datetime import date

from quantagent.agents.reporter import build_deterministic_report
from quantagent.reporting.daily import render_daily_report
from quantagent.reporting.pipeline import build_synthetic_bundle


def test_render_contains_required_sections() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    report = build_deterministic_report(bundle)
    md = render_daily_report(report, bundle)
    assert "A股市场日报" in md
    assert "Shadow Portfolio" in md
    assert "不构成投资建议" in md
    assert "买入建议" not in md
    assert report.run_id in md
