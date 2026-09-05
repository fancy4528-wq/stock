"""Unit tests for FinancialNormalizer."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.financial import FinancialNormalizer


def test_normalize_joins_three_sheets(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        [
            {
                "_sheet": "profit",
                "_request_symbol": "600519",
                "REPORT_DATE": "2024-12-31 00:00:00",
                "REPORT_TYPE": "年报",
                "REPORT_DATE_NAME": "2024年报",
                "NOTICE_DATE": "2025-03-30 00:00:00",
                "UPDATE_DATE": "2025-03-30 00:00:00",
                "TOTAL_OPERATE_INCOME": 1_000_000.0,
                "OPERATE_COST": 400_000.0,
                "OPERATE_PROFIT": 500_000.0,
                "NETPROFIT": 300_000.0,
                "PARENT_NETPROFIT": 290_000.0,
                "DEDUCT_PARENT_NETPROFIT": 280_000.0,
                "BASIC_EPS": 2.5,
            },
            {
                "_sheet": "balance",
                "_request_symbol": "600519",
                "REPORT_DATE": "2024-12-31 00:00:00",
                "REPORT_TYPE": "年报",
                "REPORT_DATE_NAME": "2024年报",
                "NOTICE_DATE": "2025-03-30 00:00:00",
                "UPDATE_DATE": "2025-03-30 00:00:00",
                "TOTAL_ASSETS": 2_000_000.0,
                "TOTAL_LIABILITIES": 800_000.0,
                "TOTAL_EQUITY": 1_200_000.0,
                "TOTAL_PARENT_EQUITY": 1_100_000.0,
                "MONETARYFUNDS": 100_000.0,
                "INVENTORY": 50_000.0,
                "ACCOUNTS_RECE": 40_000.0,
                "GOODWILL": 10_000.0,
            },
            {
                "_sheet": "cashflow",
                "_request_symbol": "600519",
                "REPORT_DATE": "2024-12-31 00:00:00",
                "REPORT_TYPE": "年报",
                "REPORT_DATE_NAME": "2024年报",
                "NOTICE_DATE": "2025-03-30 00:00:00",
                "UPDATE_DATE": "2025-03-30 00:00:00",
                "NETCASH_OPERATE": 200_000.0,
                "NETCASH_INVEST": -50_000.0,
                "NETCASH_FINANCE": -20_000.0,
                "CONSTRUCT_LONG_ASSET": 30_000.0,
            },
        ]
    )
    path = tmp_path / "fin.parquet"
    raw.write_parquet(path)
    batch = RawBatch(
        batch_id=1,
        source="akshare",
        dataset="financial_statement",
        target_date=date(2026, 9, 5),
        raw_path=path,
        row_count=raw.height,
        collected_at=datetime.now(),
        meta={"symbols": ["600519.SH"]},
    )
    out = FinancialNormalizer().normalize(batch)
    assert out.height == 1
    assert out["symbol"][0] == "600519.SH"
    assert out["period_type"][0] == "FY"
    assert out["period_end"][0] == date(2024, 12, 31)
    assert float(out["revenue"][0]) == 1_000_000.0
    assert float(out["total_assets"][0]) == 2_000_000.0
    assert float(out["cfo"][0]) == 200_000.0
    assert float(out["gross_profit"][0]) == 600_000.0
