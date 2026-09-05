"""CN / multi-market symbol normalization.

Canonical form for A-shares: ``{6 digits}.{SH|SZ|BJ}`` e.g. ``600519.SH``.
"""

from __future__ import annotations

import re

_CN_EXCHANGE_SUFFIX = re.compile(r"\.(SH|SZ|BJ|SS|XSHG|XSHE|SSE|SZSE)$", re.IGNORECASE)


def to_raw_digits(symbol: str) -> str:
    """Extract the 6-digit A-share code from a normalized or raw symbol."""
    digits = re.sub(r"\D", "", symbol)
    if len(digits) != 6:
        raise ValueError(f"Invalid CN symbol digits: {symbol!r}")
    return digits


def normalize_symbol(raw: str, *, market: str) -> str:
    """Normalize vendor symbols to ``{code}.{exchange}``.

    Accepted CN inputs include::

        '600519' / 'sh600519' / '600519.SH' / 'SH600519' / '600519.XSHG'
    """
    if market != "CN":
        raise ValueError(f"Unsupported market for normalize_symbol: {market}")

    text = raw.strip().upper().replace(" ", "")
    if not text:
        raise ValueError("Empty symbol")

    # Strip known exchange suffixes before digit extraction when present.
    m = _CN_EXCHANGE_SUFFIX.search(text)
    suffix_hint: str | None = None
    if m:
        token = m.group(1).upper()
        suffix_hint = {
            "SH": "SH",
            "SS": "SH",
            "XSHG": "SH",
            "SSE": "SH",
            "SZ": "SZ",
            "XSHE": "SZ",
            "SZSE": "SZ",
            "BJ": "BJ",
        }.get(token)
        text = text[: m.start()]

    # Prefix forms: SH600519 / SZ000001
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        prefix = text[:2]
        digits = re.sub(r"\D", "", text[2:])
        if len(digits) == 6:
            return f"{digits}.{prefix}"

    digits = re.sub(r"\D", "", text)
    if len(digits) != 6:
        raise ValueError(f"Invalid CN symbol: {raw!r}")

    if suffix_hint:
        return f"{digits}.{suffix_hint}"

    return f"{digits}.{_infer_exchange(digits)}"


def _infer_exchange(digits: str) -> str:
    """Map A-share code segments to exchange. Refs: docs/04-data-sources.md#2.4.

    Index codes that collide with stock segments (e.g. ``000300``) must be passed
    with an explicit ``.SH`` / ``.SZ`` suffix — bare digits follow the stock rules.
    """
    if digits.startswith(("60", "68", "90", "51", "58")):
        return "SH"
    if digits.startswith(("00", "30", "20", "15", "16", "18")):
        return "SZ"
    if digits.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    raise ValueError(f"Unknown exchange for CN code: {digits}")


def to_baostock_code(symbol: str) -> str:
    """Convert ``600519.SH`` → ``sh.600519``."""
    norm = normalize_symbol(symbol, market="CN")
    digits, exch = norm.split(".")
    return f"{exch.lower()}.{digits}"
