"""Unit tests for industry validators."""

from __future__ import annotations

from datetime import date

import polars as pl

from quantagent.data.validators.industry import (
    rule_ind_001_required_columns,
    rule_ind_003_unique_l1_symbol,
    rule_ind_004_valid_from,
)


def test_ind_001_and_003_pass() -> None:
    df = pl.DataFrame(
        {
            "record_type": ["industry", "membership", "membership"],
            "taxonomy_code": ["sw_2021", "sw_2021", "sw_2021"],
            "industry_code": ["801080", "801080", "801780"],
            "symbol": [None, "000725.SZ", "600036.SH"],
            "level": [1, 1, 1],
            "valid_from": [None, date(2021, 12, 13), date(2021, 12, 13)],
            "valid_to": [None, None, None],
            "source": ["akshare", "akshare", "akshare"],
        }
    )
    assert rule_ind_001_required_columns(df).status == "pass"
    assert rule_ind_003_unique_l1_symbol(df).status == "pass"
    assert rule_ind_004_valid_from(df).status == "pass"


def test_ind_003_duplicate_fails() -> None:
    df = pl.DataFrame(
        {
            "record_type": ["membership", "membership"],
            "taxonomy_code": ["sw_2021", "sw_2021"],
            "industry_code": ["801080", "801780"],
            "symbol": ["000725.SZ", "000725.SZ"],
            "level": [1, 1],
            "valid_from": [date(2021, 12, 13), date(2021, 12, 13)],
            "valid_to": [None, None],
            "source": ["akshare", "akshare"],
        }
    )
    result = rule_ind_003_unique_l1_symbol(df)
    assert result.status == "fail"
    assert "000725.SZ" in result.affected_keys
