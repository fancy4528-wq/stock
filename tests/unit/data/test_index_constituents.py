"""Unit tests for baostock index constituent helpers (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantagent.core.universe import resolve_backfill_symbols
from quantagent.data.collectors.baostock.index_constituents import baostock_code_to_symbol
from quantagent.shared.errors import ConfigError


def test_baostock_code_to_symbol() -> None:
    assert baostock_code_to_symbol("sh.600519") == "600519.SH"
    assert baostock_code_to_symbol("sz.000001") == "000001.SZ"


def test_resolve_backfill_symbols_file(tmp_path: Path) -> None:
    path = tmp_path / "syms.txt"
    path.write_text("# comment\n600519.SH\n\n000001.SZ\n", encoding="utf-8")
    syms = resolve_backfill_symbols("mvp_cn_50", symbols_file=path)
    assert syms == ["600519.SH", "000001.SZ"]


def test_resolve_backfill_symbols_missing_file() -> None:
    with pytest.raises(ConfigError, match="not found"):
        resolve_backfill_symbols("mvp_cn_50", symbols_file="no/such/file.txt")
