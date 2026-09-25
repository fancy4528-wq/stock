"""Unit tests: spot quote mapping (no network)."""

from __future__ import annotations

from quantagent.data.collectors.akshare.spot import (
    infer_limit_flags,
    quote_from_em_row,
)


def test_infer_limit_flags() -> None:
    up, down = infer_limit_flags(last=110.0, prev_close=100.0)
    assert up and not down
    up2, down2 = infer_limit_flags(last=90.0, prev_close=100.0)
    assert down2 and not up2


def test_quote_from_em_ulist_row() -> None:
    q = quote_from_em_row(
        {
            "f12": "600519",
            "f14": "贵州茅台",
            "f2": 1500.0,
            "f18": 1480.0,
            "f17": 1490.0,
            "f15": 1510.0,
            "f16": 1470.0,
            "f5": 100.0,
            "f10": 2.0,
        },
        symbol_hint="600519.SH",
    )
    assert q is not None
    assert q.symbol == "600519.SH"
    assert q.last == 1500.0
    assert q.volume == 10000.0  # 手×100
    assert q.volume_avg_5d == 5000.0
    assert q.name == "贵州茅台"


def test_quote_from_akshare_cn_columns() -> None:
    q = quote_from_em_row(
        {
            "代码": "000858",
            "名称": "五粮液",
            "最新价": 140.0,
            "昨收": 138.0,
            "今开": 139.0,
            "最高": 141.0,
            "最低": 137.0,
            "成交量": 50.0,
            "量比": 1.0,
        },
        symbol_hint="000858.SZ",
    )
    assert q is not None
    assert q.symbol == "000858.SZ"
    assert q.last == 140.0
