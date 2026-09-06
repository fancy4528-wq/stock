"""Append-only journal + Shadow Portfolio tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantagent.evaluation.journal import AppendOnlyJournal
from quantagent.evaluation.shadow import ShadowConfig, ShadowEngine
from quantagent.reporting.pipeline import build_synthetic_bars, synthetic_universe
from quantagent.shared.errors import JournalMutationError


def test_journal_append_only(tmp_path: Path) -> None:
    j = AppendOnlyJournal(tmp_path / "j.jsonl")
    j.append({"a": 1})
    j.append({"a": 2})
    assert len(j.read_all()) == 2
    with pytest.raises(JournalMutationError):
        j.update({"a": 3})
    with pytest.raises(JournalMutationError):
        j.delete(0)


@pytest.mark.asyncio
async def test_shadow_step_records_and_unfilled(tmp_path: Path) -> None:
    as_of = date(2026, 9, 1)
    symbols = synthetic_universe(20)
    bars = build_synthetic_bars(symbols, as_of)
    scores = {s: 1.0 - i * 0.01 for i, s in enumerate(symbols)}
    engine = ShadowEngine(
        tmp_path,
        cfg=ShadowConfig(baseline_n=20, factor_top_n=5, initial_cash=1_000_000.0),
    )
    recs = await engine.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
    )
    assert len(recs) == 2
    ids = {r.portfolio for r in recs}
    assert ids == {"shadow_baseline", "shadow_factor"}
    factor = next(r for r in recs if r.portfolio == "shadow_factor")
    assert factor.n_positions > 0
    # Symbol index 3 is limit-up in synthetic bars — buy should leave unfilled
    all_unfilled = [u for r in recs for u in r.unfilled]
    assert any(u.get("reason") == "limit_up_cannot_buy" for u in all_unfilled)

    # Append-only: second day adds rows
    as_of2 = date(2026, 9, 2)
    bars2 = build_synthetic_bars(symbols, as_of2, seed=8)
    await engine.step(
        as_of=as_of2,
        run_id="20260902-cn-daily",
        bars=bars2,
        baseline_symbols=symbols,
        factor_scores=scores,
    )
    baseline_lines = (tmp_path / "shadow_baseline.jsonl").read_text(encoding="utf-8").strip()
    assert len(baseline_lines.splitlines()) == 2
