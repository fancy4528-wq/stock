"""Evidence coverage and numeric traceability for deterministic reports."""

from __future__ import annotations

from datetime import date

from quantagent.agents.reporter import build_deterministic_report
from quantagent.agents.reporter.traceability import (
    assert_figures_traceable,
    bundle_trace_text,
    extract_numbers,
)
from quantagent.reporting.daily import render_daily_report
from quantagent.reporting.pipeline import build_synthetic_bundle


def test_observation_evidence_refs_subset_of_evidence_ids() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    report = build_deterministic_report(bundle)
    ev_ids = {e.evidence_id for e in report.evidence}
    for obs in report.notable_observations:
        assert set(obs.evidence_refs) <= ev_ids, obs.evidence_refs


def test_sector_and_factor_rows_have_evidence_ids() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    report = build_deterministic_report(bundle)
    ev_ids = {e.evidence_id for e in report.evidence}
    for i in range(len(bundle.sectors)):
        assert f"ev-sector-{i}" in ev_ids
    for row in bundle.factors:
        assert f"ev-factor-{row.factor}" in ev_ids


def test_extract_numbers_finds_percent_and_decimals() -> None:
    nums = extract_numbers("收于 3842.15，较前值 +0.62%，成交额 486.0 亿元")
    assert "3842.15" in nums
    assert "+0.62%" in nums


def test_twenty_numbers_traceable_in_deterministic_report() -> None:
    bundle = build_synthetic_bundle(date(2026, 9, 1))
    report = build_deterministic_report(bundle)
    full_text = render_daily_report(report, bundle)
    excerpts = [e.excerpt or "" for e in report.evidence]
    assert_figures_traceable(
        full_text,
        evidence_excerpts=excerpts,
        bundle_text=bundle_trace_text(bundle),
        sample_size=20,
    )
