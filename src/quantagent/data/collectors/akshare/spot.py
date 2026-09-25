"""Intraday spot quote collector for holdings + watchlist (P2a).

Primary: East Money ``ulist`` for requested secids only (fast).
Fallback: ``ak.stock_zh_a_spot_em`` full board filtered to symbols.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantagent.data.collectors.proxy import apply_proxy_bypass
from quantagent.data.normalizers.symbol import normalize_symbol, to_raw_digits
from quantagent.monitor.types import QuoteSnapshot
from quantagent.shared.errors import SourceUnavailableError

logger = logging.getLogger(__name__)

_EM_ULIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"
# f2 last, f3 pct%, f5 volume(手), f6 amount, f15 high, f16 low, f17 open, f18 prev,
# f12 code, f14 name, f10 volume ratio
_EM_FIELDS = "f2,f3,f5,f6,f10,f12,f14,f15,f16,f17,f18"
_LIMIT_EPS = 1e-4


def _secid(symbol: str) -> str:
    sym = normalize_symbol(symbol, market="CN")
    digits, exch = sym.split(".")
    market = {"SH": "1", "SZ": "0", "BJ": "0"}.get(exch, "1")
    return f"{market}.{digits}"


def _digits_to_symbol(code: str) -> str:
    """Best-effort exchange suffix from 6-digit code."""
    digits = to_raw_digits(code)
    if digits.startswith(("5", "6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def infer_limit_flags(
    *,
    last: float,
    prev_close: float | None,
    limit_up_ratio: float = 0.10,
    limit_down_ratio: float = -0.10,
) -> tuple[bool, bool]:
    """Mark limit-up/down from prev_close ± default board ratio (main ±10%)."""
    if prev_close is None or prev_close <= 0 or last <= 0:
        return False, False
    up_px = prev_close * (1.0 + limit_up_ratio)
    down_px = prev_close * (1.0 + limit_down_ratio)
    return last + _LIMIT_EPS >= up_px, last - _LIMIT_EPS <= down_px


def _fnum(v: Any) -> float | None:
    if v is None or v == "-" or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def quote_from_em_row(
    row: dict[str, Any],
    *,
    symbol_hint: str | None = None,
    ts: datetime | None = None,
) -> QuoteSnapshot | None:
    """Map one East Money ulist / spot row to ``QuoteSnapshot``."""
    code = str(row.get("f12") or row.get("代码") or "")
    if not code and symbol_hint:
        symbol = normalize_symbol(symbol_hint, market="CN")
    elif code:
        symbol = (
            normalize_symbol(symbol_hint, market="CN")
            if symbol_hint
            else _digits_to_symbol(code)
        )
    else:
        return None

    last = _fnum(row.get("f2") if "f2" in row else row.get("最新价"))
    if last is None or last <= 0:
        # Suspended / no quote — still emit a suspended flag when possible.
        prev = _fnum(row.get("f18") if "f18" in row else row.get("昨收"))
        name = str(row.get("f14") or row.get("名称") or "") or None
        return QuoteSnapshot(
            symbol=symbol,
            last=float(prev or 0.0),
            prev_close=prev,
            name=name,
            is_suspended=True,
            ts=ts or datetime.now(UTC),
        )

    prev = _fnum(row.get("f18") if "f18" in row else row.get("昨收"))
    open_ = _fnum(row.get("f17") if "f17" in row else row.get("今开"))
    high = _fnum(row.get("f15") if "f15" in row else row.get("最高"))
    low = _fnum(row.get("f16") if "f16" in row else row.get("最低"))
    vol_hand = _fnum(row.get("f5") if "f5" in row else row.get("成交量"))
    vol_ratio = _fnum(row.get("f10") if "f10" in row else row.get("量比"))
    name = str(row.get("f14") or row.get("名称") or "") or None
    volume = vol_hand * 100.0 if vol_hand is not None else None  # 手 → 股
    volume_avg_5d = None
    if volume is not None and vol_ratio is not None and vol_ratio > 0:
        volume_avg_5d = volume / vol_ratio

    is_up, is_down = infer_limit_flags(last=last, prev_close=prev)
    is_suspended = volume is not None and volume <= 0 and (open_ is None or open_ <= 0)

    return QuoteSnapshot(
        symbol=symbol,
        last=last,
        prev_close=prev,
        open=open_,
        high=high,
        low=low,
        volume=volume,
        volume_avg_5d=volume_avg_5d,
        is_limit_up=is_up,
        is_limit_down=is_down,
        is_suspended=is_suspended,
        name=name,
        ts=ts or datetime.now(UTC),
    )


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, TimeoutError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
def _fetch_ulist(secids: list[str]) -> list[dict[str, Any]]:
    apply_proxy_bypass()
    params = {
        "fltt": "2",
        "fields": _EM_FIELDS,
        "secids": ",".join(secids),
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(_EM_ULIST, params=params)
        resp.raise_for_status()
        payload = resp.json()
    data = (payload or {}).get("data") or {}
    diff = data.get("diff") or []
    if not isinstance(diff, list):
        return []
    return [d for d in diff if isinstance(d, dict)]


def _fetch_akshare_spot() -> list[dict[str, Any]]:
    apply_proxy_bypass()
    import akshare as ak  # noqa: PLC0415 — optional heavy import

    df = ak.stock_zh_a_spot_em()
    if df is None or getattr(df, "empty", True):
        return []
    records = df.to_dict(orient="records")
    return [r for r in records if isinstance(r, dict)]


def collect_spot_quotes(
    symbols: list[str],
    *,
    prefer: str = "ulist",
) -> dict[str, QuoteSnapshot]:
    """Fetch intraday snapshots for ``symbols`` (canonical ``600519.SH`` form).

    ``prefer``: ``ulist`` (default, targeted) or ``akshare`` (full board filter).
    """
    wanted = [normalize_symbol(s, market="CN") for s in symbols]
    if not wanted:
        return {}
    wanted_set = set(wanted)
    ts = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    source = prefer

    try:
        if prefer == "ulist":
            rows = _fetch_ulist([_secid(s) for s in wanted])
            if not rows:
                raise SourceUnavailableError("em ulist returned empty diff")
        else:
            rows = _fetch_akshare_spot()
            source = "akshare"
    except Exception as exc:  # noqa: BLE001 — try fallback once
        logger.warning("spot primary (%s) failed: %s; trying fallback", prefer, exc)
        try:
            if prefer == "ulist":
                rows = _fetch_akshare_spot()
                source = "akshare"
            else:
                rows = _fetch_ulist([_secid(s) for s in wanted])
                source = "ulist"
        except Exception as exc2:  # noqa: BLE001
            raise SourceUnavailableError(
                f"spot quotes unavailable: {type(exc2).__name__}: {exc2}"
            ) from exc2

    out: dict[str, QuoteSnapshot] = {}
    for row in rows:
        # Match by digits against wanted set.
        code = str(row.get("f12") or row.get("代码") or "")
        if not code:
            continue
        candidates = [s for s in wanted if to_raw_digits(s) == to_raw_digits(code)]
        if not candidates and source == "ulist":
            # ulist only requested symbols — accept mapped exchange
            hint = _digits_to_symbol(code)
            if hint not in wanted_set:
                # still accept if digits match any wanted
                candidates = [s for s in wanted if to_raw_digits(s) == to_raw_digits(code)]
            else:
                candidates = [hint]
        if not candidates:
            continue
        q = quote_from_em_row(row, symbol_hint=candidates[0], ts=ts)
        if q is not None:
            out[q.symbol] = q

    missing = [s for s in wanted if s not in out]
    if missing:
        logger.warning("spot missing symbols: %s (got %d/%d)", missing, len(out), len(wanted))
    if not out:
        raise SourceUnavailableError(f"no spot quotes for {wanted}")
    return out
