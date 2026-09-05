"""Unit tests for CN symbol normalization."""

from __future__ import annotations

import pytest

from quantagent.data.normalizers.symbol import normalize_symbol, to_baostock_code, to_raw_digits


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("SH600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("600519.ss", "600519.SH"),
        ("600519.XSHG", "600519.SH"),
        ("000001", "000001.SZ"),
        ("sz000001", "000001.SZ"),
        ("000001.SZ", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("688981", "688981.SH"),
        ("830799", "830799.BJ"),
        ("920001", "920001.BJ"),
        ("510300", "510300.SH"),
        ("000300.SH", "000300.SH"),
    ],
)
def test_normalize_symbol_cn(raw: str, expected: str) -> None:
    assert normalize_symbol(raw, market="CN") == expected


def test_normalize_symbol_rejects_bad_length() -> None:
    with pytest.raises(ValueError, match="Invalid CN symbol"):
        normalize_symbol("12345", market="CN")


def test_normalize_symbol_rejects_unknown_segment() -> None:
    with pytest.raises(ValueError, match="Unknown exchange"):
        normalize_symbol("999999", market="CN")


def test_to_baostock_code() -> None:
    assert to_baostock_code("600519.SH") == "sh.600519"
    assert to_baostock_code("000001") == "sz.000001"


def test_to_raw_digits() -> None:
    assert to_raw_digits("600519.SH") == "600519"
