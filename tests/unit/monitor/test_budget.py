"""Unit tests: monitor-dedicated budget (USD + L3 caps, L1 degradation)."""

from __future__ import annotations

import ast
import asyncio
from datetime import date
from pathlib import Path

from quantagent.monitor.budget import (
    MonitorBudget,
    MonitorBudgetConfig,
    MonitorBudgetExceeded,
    build_monitor_budget,
    load_monitor_budget_config,
)
from quantagent.monitor.engine import run_monitor_once, token_budget_for_monitor
from quantagent.monitor.suppression import SuppressionPolicy
from quantagent.notify.base import LogNotifier
from quantagent.positions.manual import save_position_book
from quantagent.positions.types import ManualPositionBook, PositionLot


def test_load_monitor_budget_config_defaults() -> None:
    cfg = load_monitor_budget_config()
    assert cfg.daily_usd_limit == 0.30
    assert cfg.l3_max_calls_per_day == 10
    assert cfg.on_exceed == "l1_only"


def test_zero_limit_is_l1_only() -> None:
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=0.0),
        day=date(2026, 9, 27),
    )
    assert mb.is_l1_only()
    assert not mb.allow_l2()
    assert not mb.allow_l3()
    assert mb.degradation_reason() is not None


def test_record_spend_and_persist(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    cfg = MonitorBudgetConfig(daily_usd_limit=0.30, l3_max_calls_per_day=10)
    mb = MonitorBudget(config=cfg, day=date.today(), path=path)
    mb.record_spend(0.10, layer="l2", calls=2)
    assert mb.spent_usd == 0.10
    assert mb.l2_calls == 2
    assert abs(mb.remaining_usd() - 0.20) < 1e-9
    assert path.is_file()

    reloaded = MonitorBudget.load(path, config=cfg)
    assert reloaded.spent_usd == 0.10
    assert reloaded.l2_calls == 2


def test_usd_exhaustion_blocks_l2(tmp_path: Path) -> None:
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=0.05),
        day=date.today(),
        path=tmp_path / "b.json",
    )
    mb.record_spend(0.05, layer="l2", calls=1)
    assert mb.is_l1_only()
    assert not mb.allow_l2()


def test_l3_call_cap(tmp_path: Path) -> None:
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=1.0, l3_max_calls_per_day=2),
        day=date.today(),
        path=tmp_path / "b.json",
    )
    assert mb.reserve_l3()
    assert mb.reserve_l3()
    assert not mb.reserve_l3()
    assert mb.remaining_l3_calls() == 0
    assert mb.allow_l2()  # L3 cap must not kill L2


def test_abort_on_l3_cap() -> None:
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=1.0, l3_max_calls_per_day=0, on_exceed="abort"),
        day=date.today(),
    )
    try:
        mb.reserve_l3()
        raised = False
    except MonitorBudgetExceeded:
        raised = True
    assert raised


def test_token_budget_for_monitor_uses_remaining() -> None:
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=0.30),
        day=date.today(),
        spent_usd=0.12,
    )
    tok = token_budget_for_monitor(mb)
    assert abs(tok.remaining("monitoring") - 0.18) < 1e-9
    assert tok.config.on_exceed["monitoring"] == "l1_only"


def test_engine_zero_budget_still_fires_price(tmp_path: Path) -> None:
    """ADR-0009: budget=0 → stop-loss still works, no LLM spend."""
    book = ManualPositionBook(
        account="test_budget_zero",
        as_of=date(2026, 9, 18),
        cash=10_000,
        positions=[
            PositionLot(
                symbol="600519.SH",
                name="茅台",
                industry="食品饮料",
                quantity=100,
                avg_cost=1000,
                entry_date=date(2026, 7, 1),
                entry_high=1100,
            )
        ],
    )
    path = tmp_path / "pos.yaml"
    save_position_book(book, path)
    mb = MonitorBudget(
        config=MonitorBudgetConfig(daily_usd_limit=0.0),
        day=date.today(),
        path=tmp_path / "budget.json",
    )
    result = asyncio.run(
        run_monitor_once(
            positions_path=path,
            demo=True,
            notify=True,
            notifier=LogNotifier(),
            suppression_path=tmp_path / "sup.json",
            cache_path=tmp_path / "cache.json",
            budget_path=tmp_path / "budget.json",
            monitor_budget=mb,
            policy=SuppressionPolicy(quiet_hours=[]),
            persist_peak_nav=False,
            run_news=True,
            run_l2=True,
        )
    )
    codes = {h.code.split("/")[0] for h in result.hits_raw}
    assert "PX_STOP_LOSS" in codes or "PX_LIMIT_DOWN" in codes
    assert result.budget_l1_only is True
    assert result.news_l2_mode == "l1_passthrough" or result.ran_l2 is False
    assert result.news_l2_cost_usd == 0.0
    assert any(h.cost_usd == 0 for h in result.hits_raw)
    assert any("budget" in n for n in result.notes)


def test_budget_py_has_no_agents_imports() -> None:
    root = Path(__file__).resolve().parents[3]
    src = root / "src" / "quantagent" / "monitor" / "budget.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("quantagent.agents")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("quantagent.agents")


def test_build_monitor_budget_factory(tmp_path: Path) -> None:
    mb = build_monitor_budget(
        account="x",
        path=tmp_path / "b.json",
        config=MonitorBudgetConfig(daily_usd_limit=0.2),
    )
    assert mb.config.daily_usd_limit == 0.2
    mb.record_spend(0.05, layer="l2", calls=1)
    mb2 = build_monitor_budget(path=tmp_path / "b.json", config=mb.config)
    assert mb2.spent_usd == 0.05
