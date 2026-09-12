"""Numeric traceability helpers for daily report evidence checks."""

from __future__ import annotations

import json
import re

from quantagent.agents.tools.market import ReportBundle

_NUMERIC_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?\d[\d,]*(?:\.\d+)?%?(?![A-Za-z_])",
)


def extract_numbers(text: str, *, min_len: int = 1) -> list[str]:
    """Extract display-style numeric tokens from report prose/tables."""
    found: list[str] = []
    for match in _NUMERIC_RE.finditer(text):
        token = match.group(0).strip()
        digits = re.sub(r"[^\d]", "", token)
        if len(digits) >= min_len:
            found.append(token)
    return found


def bundle_trace_text(bundle: ReportBundle) -> str:
    return json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)


def assert_figures_traceable(
    report_text: str,
    *,
    evidence_excerpts: list[str],
    bundle_text: str,
    sample_size: int = 20,
) -> None:
    """Each sampled figure must appear in evidence excerpts or bundle JSON."""
    pool = " ".join(evidence_excerpts) + " " + bundle_text
    numbers = extract_numbers(report_text, min_len=2)
    assert len(numbers) >= sample_size, f"expected >={sample_size} numbers, got {len(numbers)}"
    missing: list[str] = []
    for token in numbers[:sample_size]:
        raw = token.replace(",", "").replace("%", "")
        if token in pool or raw in pool:
            continue
        if token.endswith("%"):
            try:
                val = float(raw) / 100.0
                if f"{val:+.4f}" in pool or f"{val:.4f}" in pool:
                    continue
            except ValueError:
                pass
        else:
            try:
                val = float(raw)
                for scaled in (val, val * 1e4, val * 1e8):
                    if f"{scaled:.0f}" in pool or f"{scaled:.1f}" in pool:
                        break
                else:
                    missing.append(token)
                    continue
                continue
            except ValueError:
                pass
        missing.append(token)
    assert not missing, f"untraceable figures: {missing[:5]}"
