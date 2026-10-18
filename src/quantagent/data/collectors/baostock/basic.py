"""Baostock stock-basic rows used to fill ``security.delist_date``."""

from __future__ import annotations

import time
from datetime import date

from quantagent.core.universe.survivorship import DelistRecord
from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.symbol import to_baostock_code
from quantagent.shared.config import get_settings
from quantagent.shared.errors import QuantAgentError, SourceUnavailableError


def delist_record_from_basic(symbol: str, row: dict[str, str]) -> DelistRecord | None:
    """Map one ``query_stock_basic`` row. Listed names and blank out-dates are skipped."""
    if row.get("status") != "0":
        return None
    out_raw = (row.get("outDate") or "").strip()
    if not out_raw:
        return None
    ipo_raw = (row.get("ipoDate") or "").strip()
    if not ipo_raw:
        raise QuantAgentError(f"baostock delisted {symbol} is missing ipoDate")
    name = (row.get("code_name") or "").strip() or symbol
    record = DelistRecord(
        symbol=symbol,
        name=name,
        list_date=date.fromisoformat(ipo_raw),
        delist_date=date.fromisoformat(out_raw),
    )
    if record.delist_date < record.list_date:
        raise QuantAgentError(f"{symbol} delist_date is before list_date")
    return record


def fetch_delist_records(symbols: list[str]) -> list[DelistRecord]:
    """Query baostock once per symbol. Only status=0 rows with an out-date are returned."""
    if not symbols:
        return []
    import baostock as bs

    apply_proxy_bypass()
    login = bs.login()
    if login.error_code != "0":
        raise SourceUnavailableError(f"baostock login failed: {login.error_msg}")
    pause = get_settings().baostock_rate_limit
    found: list[DelistRecord] = []
    try:
        for index, symbol in enumerate(symbols):
            if index:
                time.sleep(pause)
            result = bs.query_stock_basic(code=to_baostock_code(symbol))
            if result.error_code != "0":
                raise SourceUnavailableError(
                    f"baostock query_stock_basic failed for {symbol}: {result.error_msg}"
                )
            if not result.next():
                continue
            row = dict(zip(result.fields, result.get_row_data(), strict=True))
            record = delist_record_from_basic(symbol, row)
            if record is not None:
                found.append(record)
    finally:
        bs.logout()
    return found
