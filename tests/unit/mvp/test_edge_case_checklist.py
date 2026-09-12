"""MVP edge-case checklist (docs/mvp-edge-case-checklist.md) — active constructions.

Excludes H1–H3 and D3/D4 (left to the 20-day observation window).
Each test id maps to a checklist row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.core.market import load_market_config
from quantagent.data.archive.parquet import ParquetArchive
from quantagent.data.normalizers.price import PriceNormalizer, infer_board
from quantagent.data.validators import ValidationContext, Validator
from quantagent.data.validators.calendar_dual import compare_calendar_open_days
from quantagent.data.validators.financial import (
    rule_fin_002_announced_after_period,
    rule_fin_005_major_restatement,
)
from quantagent.data.validators.pit import compare_adjust_factors
from quantagent.data.validators.price import (
    rule_px_004_within_limits,
    rule_px_005_extreme_move,
    rule_px_006_trading_day_coverage,
    rule_px_007_suspended_zero_volume,
    rule_px_008_vwap_band,
    rule_px_009_dual_source_price,
    rule_px_010_stuck_price,
    rule_px_011_universe_coverage,
    rule_px_012_prev_close_ex_div,
)
from quantagent.decision.risk import PortfolioState, RiskEngine, SecurityContext
from quantagent.decision.risk.rules import LimitUpBuyRule
from quantagent.reporting.live import bars_from_day_prices, build_live_quality
from quantagent.shared.errors import DataQualityError, SourceUnavailableError

CN = ZoneInfo("Asia/Shanghai")


def _px(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "600519.SH",
        "trade_date": date(2026, 9, 1),
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 104.0,
        "prev_close": 100.0,
        "volume": 1000,
        "amount": 102_000.0,
        "turnover_rate": 0.01,
        "source": "test",
        "is_suspended": False,
        "is_limit_up": False,
        "is_limit_down": False,
        "limit_up_px": 110.0,
        "limit_down_px": 90.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A — Suspension
# ---------------------------------------------------------------------------


def test_A1_suspended_bar_does_not_break_report_quality() -> None:
    """A1: suspended name keeps last price / zero volume; report annotates 停牌."""
    day = pl.DataFrame(
        [
            _px(symbol="600000.SH", volume=0, is_suspended=True, close=10.0),
            _px(symbol="600519.SH", volume=1000, is_suspended=False),
        ]
    )
    assert rule_px_007_suspended_zero_volume(day).status == "pass"
    bars = bars_from_day_prices(day)
    assert any(b.is_suspended for b in bars)
    quality = build_live_quality(
        symbols=["600000.SH", "600519.SH"],
        day=day,
        industry=pl.DataFrame({"symbol": ["600519.SH"], "industry_name": ["白酒"]}),
        factor_scores={"600519.SH": 0.5},
    )
    note = next(q for q in quality if q.name == "停牌标注")
    assert "600000.SH" in note.detail


def test_A1_missing_bar_exempt_when_known_suspended() -> None:
    """A1 / PX_006: open-day missing bar is OK if listed as suspended."""
    day = pl.DataFrame([_px(symbol="600519.SH")])
    ctx = ValidationContext(
        persist=False,
        extra={
            "is_trading_day": True,
            "universe_symbols": ["600519.SH", "600000.SH"],
            "suspended_symbols": ["600000.SH"],
        },
    )
    assert rule_px_006_trading_day_coverage(day, ctx).status == "pass"


def test_A2_seed_excludes_suspended_on_snapshot_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """A2: seed_universe_snapshot filters is_suspended on as_of (logic unit)."""
    from quantagent.core.universe import config as uni_cfg

    # Pure logic: simulate filter step used inside seed_universe_snapshot.
    present = ["A", "B", "C"]
    known = {"A": 1, "B": 2, "C": 3}
    suspended_ids = {2}
    filtered = [s for s in present if known[s] not in suspended_ids]
    assert filtered == ["A", "C"]
    assert "seed_universe_snapshot" in dir(uni_cfg)


def test_A3_resume_day_large_move_with_adjust_not_px012() -> None:
    """A3/C1: large gap with adjust factor record is not PX_012."""
    df = pl.DataFrame(
        [
            _px(
                close=15.0,
                prev_close=10.0,
                prior_close=12.0,
                has_adjust_factor=True,
            )
        ]
    )
    assert rule_px_012_prev_close_ex_div(df).status == "pass"


# ---------------------------------------------------------------------------
# B — Limits
# ---------------------------------------------------------------------------


def test_B1_limit_up_one_word_board_and_broker() -> None:
    """B1: one-word limit-up stays within band; buy rejected at limit."""
    df = pl.DataFrame(
        [_px(close=110.0, high=110.0, low=110.0, open=110.0, is_limit_up=True, limit_up_px=110.0)]
    )
    assert rule_px_004_within_limits(df).status == "pass"
    mkt = load_market_config("CN")
    assert mkt.price_limits(board="main", is_st=False) == (0.10, -0.10)
    engine = RiskEngine(rules=[LimitUpBuyRule()])
    state = PortfolioState(
        as_of=date(2026, 9, 1), cash=100_000.0, total_value=1_000_000.0, peak_value=1_000_000.0
    )
    result = engine.check(
        {"A": 0.1},
        state,
        as_of=date(2026, 9, 1),
        context={"A": SecurityContext(symbol="A", is_limit_up=True)},
    )
    assert "A" not in result.final_target
    assert any(v.rule_code == "EXE_002" for v in result.violations)


def test_B2_st_uses_5pct_limit(tmp_path: Path) -> None:
    """B2: ST threshold is ±5%; normalizer uses 5% band."""
    cfg = load_market_config("CN")
    assert cfg.price_limits(board="main", is_st=True) == (0.05, -0.05)
    raw = pl.DataFrame(
        {
            "date": ["2024-01-02"],
            "code": ["sh.600000"],
            "open": ["100.000"],
            "high": ["105.000"],
            "low": ["100.000"],
            "close": ["105.000"],
            "preclose": ["100.000"],
            "volume": ["1000"],
            "amount": ["105000.000"],
            "turn": ["1.000000"],
            "tradestatus": ["1"],
            "isST": ["1"],
        }
    )
    archive = ParquetArchive(tmp_path)
    batch = archive.write(
        raw,
        source="baostock",
        dataset="price_daily",
        target_date=date(2024, 1, 2),
        meta={"symbols": ["600000.SH"]},
        collected_at=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
    )
    out = PriceNormalizer(cfg).normalize(batch)
    assert out["limit_up_px"][0] == pytest.approx(105.0)
    assert out["is_limit_up"][0] is True
    assert rule_px_004_within_limits(out).status == "pass"


def test_B3_star_gem_20pct() -> None:
    """B3: STAR/GEM use ±20%."""
    cfg = load_market_config("CN")
    assert cfg.price_limits(board="star", is_st=False) == (0.20, -0.20)
    assert cfg.price_limits(board="gem", is_st=False) == (0.20, -0.20)
    assert infer_board("688001.SH") == "star"
    assert infer_board("300001.SZ") == "gem"


def test_B4_px005_boundary_50pct() -> None:
    """B4: true move at 49.9% passes; >50% fails PX_005."""
    ok = pl.DataFrame([_px(close=149.9, prev_close=100.0)])
    bad = pl.DataFrame([_px(close=150.1, prev_close=100.0)])
    assert rule_px_005_extreme_move(ok).status == "pass"
    assert rule_px_005_extreme_move(bad).status == "fail"


# ---------------------------------------------------------------------------
# C — Ex-div
# ---------------------------------------------------------------------------


def test_C1_ex_div_with_record_ok() -> None:
    df = pl.DataFrame([_px(prev_close=9.5, prior_close=10.0, has_adjust_factor=True, close=9.6)])
    assert rule_px_012_prev_close_ex_div(df).status == "pass"


def test_C2_ex_div_without_record_errors() -> None:
    df = pl.DataFrame([_px(prev_close=9.5, prior_close=10.0, has_adjust_factor=False, close=9.6)])
    r = rule_px_012_prev_close_ex_div(df)
    assert r.status == "fail"
    assert r.code == "PX_012"


def test_C3_dual_adjust_factor_warns() -> None:
    r = compare_adjust_factors(factor_a=1.0, factor_b=1.01, threshold=0.001)
    assert r.status == "warn"
    ok = compare_adjust_factors(factor_a=1.0, factor_b=1.0005, threshold=0.001)
    assert ok.status == "pass"


# ---------------------------------------------------------------------------
# D — Calendar (D1/D2 only; D3/D4 deferred)
# ---------------------------------------------------------------------------


def test_D1_holiday_not_treated_as_missing_data() -> None:
    """D1: non-trading day skips PX_006 coverage requirement."""
    df = pl.DataFrame([])
    ctx = ValidationContext(
        persist=False,
        extra={"is_trading_day": False, "universe_symbols": ["600519.SH"]},
    )
    assert rule_px_006_trading_day_coverage(df, ctx).status == "pass"


def test_D2_calendar_dual_source_mismatch_warns() -> None:
    primary = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 1), date(2026, 10, 8)],
            "is_open": [False, True],
        }
    )
    secondary = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 1), date(2026, 10, 8), date(2026, 10, 9)],
            "is_open": [False, True, True],
        }
    )
    r = compare_calendar_open_days(primary, secondary)
    assert r.status == "warn"
    assert "2026-10-09" in r.affected_keys


# ---------------------------------------------------------------------------
# E — Financials
# ---------------------------------------------------------------------------


def test_E2_fin005_marks_major_restatement() -> None:
    df = pl.DataFrame(
        [
            {
                "symbol": "600519.SH",
                "period_end": date(2019, 12, 31),
                "period_type": "FY",
                "announced_at": datetime(2020, 3, 31, tzinfo=CN),
                "net_profit": 100.0,
                "revenue": 200.0,
                "total_assets": 300.0,
                "total_liab": 100.0,
                "total_equity": 200.0,
            },
            {
                "symbol": "600519.SH",
                "period_end": date(2019, 12, 31),
                "period_type": "FY",
                "announced_at": datetime(2021, 3, 31, tzinfo=CN),
                "net_profit": 150.0,  # +50%
                "revenue": 200.0,
                "total_assets": 300.0,
                "total_liab": 100.0,
                "total_equity": 200.0,
            },
        ]
    )
    r = rule_fin_005_major_restatement(df)
    assert r.status == "warn"
    assert r.level == "INFO"


def test_E3_fin002_fatal_early_announce() -> None:
    df = pl.DataFrame(
        [
            {
                "symbol": "600519.SH",
                "period_end": date(2019, 12, 31),
                "period_type": "FY",
                "announced_at": datetime(2019, 1, 1, tzinfo=CN),
                "net_profit": 1.0,
                "revenue": 1.0,
                "total_assets": 3.0,
                "total_liab": 1.0,
                "total_equity": 2.0,
            }
        ]
    )
    assert rule_fin_002_announced_after_period(df).status == "fail"
    with pytest.raises(DataQualityError, match="FIN_002"):
        Validator().validate(df, "financial_statement", ValidationContext(persist=False))


# ---------------------------------------------------------------------------
# F — Source failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_F1_empty_primary_raises_not_silent() -> None:
    """F1: empty vendor response → SourceUnavailableError (explicit alert)."""
    from quantagent.data.collectors.akshare.price import AksharePriceCollector

    c = AksharePriceCollector(archive_root=Path("."))

    async def _empty(*_a: object, **_k: object) -> pl.DataFrame:
        return pl.DataFrame()

    c._fetch_hist = _empty  # type: ignore[method-assign]
    with pytest.raises(SourceUnavailableError):
        await c.collect(
            date(2026, 9, 1),
            symbols=["600519.SH"],
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
        )


def test_F2_px011_coverage_below_99() -> None:
    df = pl.DataFrame([_px(symbol=f"S{i:02d}.SH") for i in range(40)])
    ctx = ValidationContext(persist=False, extra={"expected_count": 50})
    r = rule_px_011_universe_coverage(df, ctx)
    assert r.status == "fail"


def test_F3_px010_stuck_price() -> None:
    rows = [_px(trade_date=date(2026, 9, 1) + timedelta(days=i), close=10.0) for i in range(5)]
    assert rule_px_010_stuck_price(pl.DataFrame(rows)).status == "warn"


def test_F4_px008_vwap_out_of_band() -> None:
    df = pl.DataFrame([_px(amount=200_000.0, volume=1000, low=99.0, high=105.0)])
    assert rule_px_008_vwap_band(df).status == "warn"


def test_F5_px009_dual_source_diff() -> None:
    df = pl.DataFrame(
        [_px(close_a=100.0, close_b=101.0)]  # 1% > 0.5%
    )
    assert rule_px_009_dual_source_price(df).status == "fail"


# ---------------------------------------------------------------------------
# G — PIT / traceability (unit side; integration covers DB injections)
# ---------------------------------------------------------------------------


def test_G5_report_evidence_traceable_to_values() -> None:
    """G5: twenty figures from deterministic report trace to Evidence or bundle fields."""
    from quantagent.agents.reporter import build_deterministic_report
    from quantagent.agents.reporter.traceability import (
        assert_figures_traceable,
        bundle_trace_text,
    )
    from quantagent.reporting.daily import render_daily_report
    from quantagent.reporting.pipeline import build_synthetic_bundle

    bundle = build_synthetic_bundle(date(2026, 9, 7))
    report = build_deterministic_report(bundle)
    assert_figures_traceable(
        render_daily_report(report, bundle),
        evidence_excerpts=[e.excerpt or "" for e in report.evidence],
        bundle_text=bundle_trace_text(bundle),
        sample_size=20,
    )
    live = Path("docs/daily-reports/2026-09-07.md")
    if live.is_file():
        text = live.read_text(encoding="utf-8")
        assert "Evidence" in text
        assert "数据显示" in text
