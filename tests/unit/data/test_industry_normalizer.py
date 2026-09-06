"""Unit tests for IndustryNormalizer."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.industry import IndustryNormalizer


def _raw_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "_kind": "taxonomy_l1",
                "行业代码": "801080.SI",
                "行业名称": "电子",
                "成分个数": 10,
            },
            {
                "_kind": "taxonomy_l1",
                "行业代码": "801780.SI",
                "行业名称": "银行",
                "成分个数": 5,
            },
            {
                "_kind": "taxonomy_l2",
                "行业代码": "801081.SI",
                "行业名称": "半导体",
                "上级行业": "电子",
                "成分个数": 3,
            },
            {
                "_kind": "member_l1",
                "_industry_code": "801080",
                "证券代码": "000725",
                "证券名称": "京东方Ａ",
                "计入日期": "2021-12-13",
            },
            {
                "_kind": "member_l1",
                "_industry_code": "801780",
                "证券代码": "600036.SH",
                "证券名称": "招商银行",
                "计入日期": "2021-12-13",
            },
            {
                "_kind": "member_l1",
                "_industry_code": "801080",
                "证券代码": "002415",
                "证券名称": "海康威视",
                "计入日期": "2022-01-01",
            },
        ]
    )


def test_normalize_taxonomy_and_memberships(tmp_path: Path) -> None:
    raw = _raw_frame()
    path = tmp_path / "ind.parquet"
    raw.write_parquet(path)
    batch = RawBatch(
        batch_id=1,
        source="akshare",
        dataset="security_industry",
        target_date=date(2026, 9, 6),
        raw_path=path,
        row_count=raw.height,
        collected_at=datetime.now(),
        meta={"taxonomy": "sw_2021", "filter_symbols": ["000725.SZ", "600036.SH"]},
    )
    out = IndustryNormalizer().normalize(batch)
    industries = out.filter(pl.col("record_type") == "industry")
    members = out.filter(pl.col("record_type") == "membership")
    assert industries.height == 3
    assert set(industries.filter(pl.col("level") == 1)["industry_code"].to_list()) == {
        "801080",
        "801780",
    }
    l2 = industries.filter(pl.col("industry_code") == "801081").to_dicts()[0]
    assert l2["parent_code"] == "801080"
    assert members.height == 2  # filtered; 002415 dropped
    assert set(members["symbol"].to_list()) == {"000725.SZ", "600036.SH"}
    boe = members.filter(pl.col("symbol") == "000725.SZ").to_dicts()[0]
    assert boe["industry_name"] == "电子"
    assert boe["valid_from"] == date(2021, 12, 13)
