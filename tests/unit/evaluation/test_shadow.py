"""Append-only journal + Shadow Portfolio tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantagent.evaluation.journal import AppendOnlyJournal
from quantagent.evaluation.shadow import ShadowConfig, ShadowEngine, scores_from_brief
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


def test_journal_has_as_of(tmp_path: Path) -> None:
    j = AppendOnlyJournal(tmp_path / "j.jsonl")
    j.append({"as_of": "2026-09-01", "run_id": "r1"})
    assert j.has_as_of(date(2026, 9, 1))
    assert j.has_as_of("2026-09-01", run_id="r1")
    assert not j.has_as_of("2026-09-01", run_id="other")
    assert j.latest_for_as_of(date(2026, 9, 1))["run_id"] == "r1"


@pytest.mark.asyncio
async def test_shadow_step_records_and_unfilled(tmp_path: Path) -> None:
    as_of = date(2026, 9, 1)
    symbols = synthetic_universe(20)
    bars = build_synthetic_bars(symbols, as_of)
    scores = {s: 1.0 - i * 0.01 for i, s in enumerate(symbols)}
    # Distinct rankings so factor / quant / agent Top-N diverge
    quant_scores = {s: float((i * 11 + 5) % 20) for i, s in enumerate(symbols)}
    agent_scores = {s: float(i) for i, s in enumerate(symbols)}
    engine = ShadowEngine(
        tmp_path,
        cfg=ShadowConfig(
            baseline_n=20,
            factor_top_n=5,
            quant_top_n=5,
            agent_top_n=5,
            fused_top_n=5,
            initial_cash=1_000_000.0,
        ),
    )
    recs = await engine.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores=quant_scores,
        agent_scores=agent_scores,
    )
    assert len(recs) == 6
    ids = {r.portfolio for r in recs}
    assert ids == {
        "shadow_baseline",
        "shadow_factor",
        "shadow_quant",
        "shadow_agent",
        "shadow_fused",
        "shadow_fused_norisk",
    }
    factor = next(r for r in recs if r.portfolio == "shadow_factor")
    quant = next(r for r in recs if r.portfolio == "shadow_quant")
    agent = next(r for r in recs if r.portfolio == "shadow_agent")
    fused = next(r for r in recs if r.portfolio == "shadow_fused")
    fused_nr = next(r for r in recs if r.portfolio == "shadow_fused_norisk")
    assert factor.n_positions > 0
    assert quant.n_positions > 0
    assert agent.n_positions > 0
    assert fused.n_positions > 0
    assert fused_nr.n_positions > 0
    assert set(factor.weights) != set(agent.weights)
    assert set(quant.weights) != set(factor.weights)
    assert "risk_skipped" in fused_nr.notes
    assert any(n.startswith("risk:") for n in fused.notes)
    # Limit-up name filtered by RiskEngine on fused, kept on norisk target
    limit_up_sym = symbols[3]
    if limit_up_sym in fused_nr.weights:
        assert limit_up_sym not in fused.weights
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
        quant_scores=quant_scores,
        agent_scores=agent_scores,
    )
    baseline_lines = (tmp_path / "shadow_baseline.jsonl").read_text(encoding="utf-8").strip()
    assert len(baseline_lines.splitlines()) == 2
    agent_lines = (tmp_path / "shadow_agent.jsonl").read_text(encoding="utf-8").strip()
    assert len(agent_lines.splitlines()) == 2
    quant_lines = (tmp_path / "shadow_quant.jsonl").read_text(encoding="utf-8").strip()
    assert len(quant_lines.splitlines()) == 2
    fused_lines = (tmp_path / "shadow_fused.jsonl").read_text(encoding="utf-8").strip()
    assert len(fused_lines.splitlines()) == 2

    status = engine.latest_status()
    assert len(status) == 6
    assert all("ret_cum" in row for row in status)


@pytest.mark.asyncio
async def test_shadow_step_idempotent_same_as_of(tmp_path: Path) -> None:
    as_of = date(2026, 9, 1)
    symbols = synthetic_universe(10)
    bars = build_synthetic_bars(symbols, as_of)
    scores = {s: 1.0 - i * 0.01 for i, s in enumerate(symbols)}
    engine = ShadowEngine(
        tmp_path,
        cfg=ShadowConfig(
            baseline_n=10,
            factor_top_n=3,
            quant_top_n=3,
            agent_top_n=3,
            fused_top_n=3,
            initial_cash=1_000_000.0,
        ),
    )
    first = await engine.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores=scores,
        agent_scores=scores,
    )
    second = await engine.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores=scores,
        agent_scores=scores,
    )
    assert len(second) == 6
    assert all("idempotent_skip" in r.notes for r in second)
    baseline_lines = (tmp_path / "shadow_baseline.jsonl").read_text(encoding="utf-8").strip()
    assert len(baseline_lines.splitlines()) == 1
    assert first[0].nav == second[0].nav


@pytest.mark.asyncio
async def test_shadow_quant_catchup_without_duplicating_peers(tmp_path: Path) -> None:
    """Adding shadow_quant later must not re-append peers for same as_of."""
    as_of = date(2026, 9, 1)
    symbols = synthetic_universe(10)
    bars = build_synthetic_bars(symbols, as_of)
    scores = {s: 1.0 - i * 0.01 for i, s in enumerate(symbols)}
    cfg = ShadowConfig(
        baseline_n=10, factor_top_n=3, quant_top_n=3, agent_top_n=3, fused_top_n=3
    )

    legacy = ShadowEngine(tmp_path, cfg=cfg)
    quant_state = legacy._states.pop("shadow_quant")
    await legacy.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores={},
        agent_scores=scores,
    )
    _ = quant_state
    quant_path = tmp_path / "shadow_quant.jsonl"
    if quant_path.exists():
        quant_path.unlink()

    engine2 = ShadowEngine(tmp_path, cfg=cfg)
    engine2.load_history_metrics()
    recs = await engine2.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores=scores,
        agent_scores=scores,
    )
    by_pid = {r.portfolio: r for r in recs}
    assert "idempotent_skip" in by_pid["shadow_baseline"].notes
    assert "idempotent_skip" in by_pid["shadow_factor"].notes
    assert "idempotent_skip" in by_pid["shadow_agent"].notes
    assert "idempotent_skip" not in by_pid["shadow_quant"].notes
    assert by_pid["shadow_quant"].n_positions > 0
    baseline_lines = (tmp_path / "shadow_baseline.jsonl").read_text(encoding="utf-8").strip()
    assert len(baseline_lines.splitlines()) == 1
    quant_lines = (tmp_path / "shadow_quant.jsonl").read_text(encoding="utf-8").strip()
    assert len(quant_lines.splitlines()) == 1


@pytest.mark.asyncio
async def test_shadow_fused_catchup_without_duplicating_peers(tmp_path: Path) -> None:
    """New fused portfolios catch up without rewriting older peers."""
    as_of = date(2026, 9, 1)
    symbols = synthetic_universe(10)
    bars = build_synthetic_bars(symbols, as_of)
    scores = {s: 1.0 - i * 0.01 for i, s in enumerate(symbols)}
    cfg = ShadowConfig(
        baseline_n=10, factor_top_n=3, quant_top_n=3, agent_top_n=3, fused_top_n=3
    )

    legacy = ShadowEngine(tmp_path, cfg=cfg)
    for pid in ("shadow_fused", "shadow_fused_norisk"):
        legacy._states.pop(pid)
    await legacy.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores=scores,
        agent_scores=scores,
    )
    for pid in ("shadow_fused", "shadow_fused_norisk"):
        path = tmp_path / f"{pid}.jsonl"
        if path.exists():
            path.unlink()

    engine2 = ShadowEngine(tmp_path, cfg=cfg)
    engine2.load_history_metrics()
    recs = await engine2.step(
        as_of=as_of,
        run_id="20260901-cn-daily",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores=scores,
        quant_scores=scores,
        agent_scores=scores,
    )
    by_pid = {r.portfolio: r for r in recs}
    assert "idempotent_skip" in by_pid["shadow_baseline"].notes
    assert "idempotent_skip" in by_pid["shadow_quant"].notes
    assert "idempotent_skip" not in by_pid["shadow_fused"].notes
    assert "idempotent_skip" not in by_pid["shadow_fused_norisk"].notes
    assert by_pid["shadow_fused"].n_positions > 0
    assert by_pid["shadow_fused_norisk"].n_positions > 0
    baseline_lines = (tmp_path / "shadow_baseline.jsonl").read_text(encoding="utf-8").strip()
    assert len(baseline_lines.splitlines()) == 1


@pytest.mark.asyncio
async def test_shadow_agent_empty_scores_notes(tmp_path: Path) -> None:
    as_of = date(2026, 9, 1)
    symbols = synthetic_universe(8)
    bars = build_synthetic_bars(symbols, as_of)
    engine = ShadowEngine(
        tmp_path,
        cfg=ShadowConfig(
            baseline_n=8, factor_top_n=3, quant_top_n=3, agent_top_n=3, fused_top_n=3
        ),
    )
    recs = await engine.step(
        as_of=as_of,
        run_id="r1",
        bars=bars,
        baseline_symbols=symbols,
        factor_scores={s: 1.0 for s in symbols},
        quant_scores={},
        agent_scores={},
    )
    agent = next(r for r in recs if r.portfolio == "shadow_agent")
    quant = next(r for r in recs if r.portfolio == "shadow_quant")
    fused = next(r for r in recs if r.portfolio == "shadow_fused")
    fused_nr = next(r for r in recs if r.portfolio == "shadow_fused_norisk")
    assert "no_agent_scores" in agent.notes
    assert agent.n_positions == 0
    assert "no_quant_scores" in quant.notes
    assert quant.n_positions == 0
    assert "no_fused_scores" in fused.notes
    assert "no_fused_scores" in fused_nr.notes
    assert fused.n_positions == 0
    assert fused_nr.n_positions == 0


@pytest.mark.asyncio
async def test_shadow_latest_status_empty(tmp_path: Path) -> None:
    engine = ShadowEngine(tmp_path, cfg=ShadowConfig(baseline_n=5, factor_top_n=2))
    from quantagent.core.market import load_market_config
    from quantagent.evaluation.shadow.engine import ShadowPortfolioState

    market = load_market_config("CN")
    st = ShadowPortfolioState(
        "empty",  # type: ignore[arg-type]
        cfg=ShadowConfig(baseline_n=5, factor_top_n=2),
        market=market,
        journal=AppendOnlyJournal(tmp_path / "empty.jsonl"),
    )
    engine._states = {"empty": st}  # type: ignore[assignment]
    rows = engine.latest_status()
    assert rows == [
        {
            "portfolio": "empty",
            "ret_1d": 0.0,
            "ret_cum": 0.0,
            "max_drawdown": 0.0,
            "n_positions": 0,
        }
    ]


def test_scores_from_brief_empty() -> None:
    assert scores_from_brief(None) == {}
