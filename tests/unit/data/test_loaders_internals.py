"""Mock coverage for Industry / Financial / Adjust loader internals."""

from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quantagent.data.loaders.adjust import AdjustLoader
from quantagent.data.loaders.adjust import _infer_board as adj_board
from quantagent.data.loaders.financial import FinancialLoader
from quantagent.data.loaders.industry import IndustryLoader
from quantagent.data.validators.report import RuleResult, ValidationReport
from quantagent.shared.errors import DataError, DataQualityError

CN_TZ = ZoneInfo("Asia/Shanghai")


def _begin(engine: MagicMock, conn: MagicMock) -> None:
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    engine.begin.return_value = ctx


def test_adjust_board_and_load_paths() -> None:
    assert adj_board("688001") == "star"
    assert adj_board("300001") == "gem"
    assert adj_board("430001") == "bse"
    assert adj_board("600000") == "main"

    loader = AdjustLoader(engine=MagicMock())
    with pytest.raises(DataError, match="empty"):
        loader.load(pl.DataFrame(), source="baostock")

    announced = datetime.combine(date(2026, 6, 15), time(15, 0), tzinfo=CN_TZ)
    df = pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 6, 15)],
            "factor_qfq": [1.0],
            "factor_hfq": [1.0],
            "announced_at": [announced],
            "source": ["baostock"],
        }
    )
    report = ValidationReport(
        dataset="adjust_factor",
        check_date=date(2026, 6, 15),
        results=[RuleResult(code="X", level="FATAL", status="fail", detail="bad")],
    )
    with patch.object(loader, "_start_batch", return_value=1), patch.object(
        loader, "_finish_batch"
    ):
        with pytest.raises(DataQualityError, match="blocking"):
            loader.load(df, source="baostock", validate=False, report=report)

    conn = MagicMock()
    _begin(loader._engine, conn)
    with (
        patch.object(loader, "_start_batch", return_value=7),
        patch.object(loader, "_finish_batch") as finish,
        patch("quantagent.data.loaders.adjust.persist_rule_results"),
        patch.object(loader, "_ensure_securities", return_value={"600519.SH": 1}),
        patch.object(loader, "_insert_factors", return_value=1),
    ):
        out = loader.load(df, source="baostock", validate=True, target_date=date(2026, 6, 15))
    assert out["rows_loaded"] == 1
    finish.assert_called_once_with(7, status="success", row_count=1)

    conn.execute.return_value.scalar_one.return_value = 9
    assert loader._ensure_securities(conn, df) == {"600519.SH": 9}


def test_financial_insert_and_approx() -> None:
    loader = FinancialLoader(engine=MagicMock())
    assert FinancialLoader._approx_eq(None, None)
    assert not FinancialLoader._approx_eq(None, 1)
    assert FinancialLoader._approx_eq(1.0, 1.001)
    assert not FinancialLoader._approx_eq(1.0, 2.0)
    assert not FinancialLoader._approx_eq("a", 1)

    announced = datetime(2020, 4, 1, tzinfo=CN_TZ)
    df = pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "period_end": [date(2019, 12, 31)],
            "period_type": ["annual"],
            "announced_at": [announced],
            "net_profit": [100.0],
            "revenue": [200.0],
            "total_assets": [300.0],
        }
    )
    conn = MagicMock()
    # first revision
    select = MagicMock()
    select.mappings.return_value.all.return_value = []
    conn.execute.side_effect = [select, MagicMock()]
    assert loader._insert_statements(conn, df, id_map={"600519.SH": 1}, source="akshare") == 1

    # skip identical announced_at
    select2 = MagicMock()
    select2.mappings.return_value.all.return_value = [
        {
            "revision": 1,
            "announced_at": announced,
            "net_profit": 100.0,
            "revenue": 200.0,
            "total_assets": 300.0,
        }
    ]
    conn.execute.side_effect = [select2]
    assert loader._insert_statements(conn, df, id_map={"600519.SH": 1}, source="akshare") == 0

    # skip same nums with older announce
    older = datetime(2019, 1, 1, tzinfo=CN_TZ)
    df_old = df.with_columns(pl.lit(older).alias("announced_at"))
    select3 = MagicMock()
    select3.mappings.return_value.all.return_value = [
        {
            "revision": 1,
            "announced_at": announced,
            "net_profit": 100.0,
            "revenue": 200.0,
            "total_assets": 300.0,
        }
    ]
    conn.execute.side_effect = [select3]
    assert loader._insert_statements(conn, df_old, id_map={"600519.SH": 1}, source="akshare") == 0

    # restatement bump
    newer = datetime(2021, 1, 1, tzinfo=CN_TZ)
    df_new = df.with_columns(
        [
            pl.lit(newer).alias("announced_at"),
            pl.lit(999.0).alias("net_profit"),
        ]
    )
    select4 = MagicMock()
    select4.mappings.return_value.all.return_value = [
        {
            "revision": 1,
            "announced_at": announced,
            "net_profit": 100.0,
            "revenue": 200.0,
            "total_assets": 300.0,
        }
    ]
    conn.execute.side_effect = [select4, MagicMock()]
    assert loader._insert_statements(conn, df_new, id_map={"600519.SH": 1}, source="akshare") == 1

    conn2 = MagicMock()
    conn2.execute.return_value.scalar_one.return_value = 3
    assert loader._ensure_securities(conn2, df) == {"600519.SH": 3}

    # successful load path
    report = ValidationReport(
        dataset="financial_statement",
        check_date=date(2020, 4, 1),
        results=[],
    )
    _begin(loader._engine, MagicMock())
    with (
        patch.object(loader, "_start_batch", return_value=2),
        patch.object(loader, "_finish_batch"),
        patch("quantagent.data.loaders.financial.persist_rule_results"),
        patch.object(loader, "_ensure_securities", return_value={"600519.SH": 1}),
        patch.object(loader, "_insert_statements", return_value=1),
    ):
        out = loader.load(df, source="akshare", validate=False, report=report)
    assert out["status"] == "success"


def test_industry_membership_flow() -> None:
    loader = IndustryLoader(engine=MagicMock())
    industries = pl.DataFrame(
        {
            "record_type": ["industry"],
            "taxonomy_code": ["sw_2021"],
            "industry_code": ["801010"],
            "industry_name": ["农林牧渔"],
            "level": [1],
            "parent_code": [None],
        }
    )
    memberships = pl.DataFrame(
        {
            "record_type": ["membership"],
            "taxonomy_code": ["sw_2021"],
            "industry_code": ["801010"],
            "symbol": ["600519.SH"],
            "level": [1],
            "valid_from": [date(2020, 1, 1)],
            "source": ["akshare"],
        }
    )
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 10
    assert loader._ensure_taxonomies(conn, industries) == {"sw_2021": 10}
    assert loader._upsert_industries(conn, industries, tax_map={"sw_2021": 10}) == 1
    assert loader._upsert_industries(conn, pl.DataFrame(), tax_map={}) == 0

    conn.execute.return_value.scalar_one.return_value = 5
    assert loader._ensure_securities(conn, memberships) == {"600519.SH": 5}

    conn.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(DataError, match="industry node missing"):
        loader._industry_id(conn, taxonomy_id=1, industry_code="x")
    conn.execute.return_value.scalar_one_or_none.return_value = 77
    assert loader._industry_id(conn, taxonomy_id=1, industry_code="801010") == 77

    # empty memberships
    assert (
        loader._apply_memberships(
            conn,
            pl.DataFrame(),
            tax_map={},
            id_map={},
            source="akshare",
            snapshot_date=date(2020, 6, 1),
        )
        == 0
    )

    # first insert (no open rows)
    open_q = MagicMock()
    open_q.mappings.return_value.all.return_value = []
    conn.execute.side_effect = [open_q, MagicMock()]
    with patch.object(loader, "_industry_id", return_value=77):
        n = loader._apply_memberships(
            conn,
            memberships,
            tax_map={"sw_2021": 10},
            id_map={"600519.SH": 5},
            source="akshare",
            snapshot_date=date(2020, 6, 1),
        )
    assert n == 1

    # same open → skip
    open_same = MagicMock()
    open_same.mappings.return_value.all.return_value = [
        {"industry_id": 77, "valid_from": date(2019, 1, 1), "level": 1}
    ]
    conn.execute.side_effect = [open_same]
    with patch.object(loader, "_industry_id", return_value=77):
        assert (
            loader._apply_memberships(
                conn,
                memberships,
                tax_map={"sw_2021": 10},
                id_map={"600519.SH": 5},
                source="akshare",
                snapshot_date=date(2020, 6, 1),
            )
            == 0
        )

    # reclassify: close prior + insert
    open_other = MagicMock()
    open_other.mappings.return_value.all.return_value = [
        {"industry_id": 88, "valid_from": date(2019, 1, 1), "level": 1}
    ]
    conn.execute.side_effect = [open_other, MagicMock(), MagicMock()]
    with patch.object(loader, "_industry_id", return_value=77):
        assert (
            loader._apply_memberships(
                conn,
                memberships,
                tax_map={"sw_2021": 10},
                id_map={"600519.SH": 5},
                source="akshare",
                snapshot_date=date(2020, 6, 1),
            )
            == 1
        )

    # successful load with precomputed report
    frame = pl.concat([industries, memberships], how="diagonal_relaxed")
    report = ValidationReport(dataset="security_industry", check_date=date(2020, 6, 1), results=[])
    _begin(loader._engine, MagicMock())
    with (
        patch.object(loader, "_start_batch", return_value=3),
        patch.object(loader, "_finish_batch"),
        patch("quantagent.data.loaders.industry.persist_rule_results"),
        patch.object(loader, "_ensure_taxonomies", return_value={"sw_2021": 10}),
        patch.object(loader, "_upsert_industries", return_value=1),
        patch.object(loader, "_ensure_securities", return_value={"600519.SH": 5}),
        patch.object(loader, "_apply_memberships", return_value=1),
    ):
        out = loader.load(
            frame,
            source="akshare",
            validate=False,
            report=report,
            snapshot_date=date(2020, 6, 1),
        )
    assert out["industries_upserted"] == 1
    assert out["memberships_applied"] == 1
