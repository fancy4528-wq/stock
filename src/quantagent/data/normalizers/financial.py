"""Normalize East Money financial sheets → canonical ``financial_statement`` rows."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.errors import DataError

CN_TZ = ZoneInfo("Asia/Shanghai")

CANONICAL_FIN_COLUMNS = [
    "symbol",
    "period_end",
    "period_type",
    "announced_at",
    "report_type",
    "revenue",
    "operating_cost",
    "gross_profit",
    "operating_profit",
    "net_profit",
    "net_profit_attr",
    "net_profit_deducted",
    "eps",
    "total_assets",
    "total_liab",
    "total_equity",
    "equity_attr",
    "cash_and_equiv",
    "inventory",
    "accounts_recv",
    "goodwill",
    "cfo",
    "cfi",
    "cff",
    "capex",
    "source",
]

_PERIOD_MAP = {
    "一季报": "Q1",
    "一季度": "Q1",
    "中报": "H1",
    "半年": "H1",
    "三季报": "Q3",
    "三季度": "Q3",
    "年报": "FY",
    "年度": "FY",
}


def _map_period_type(report_type: object, report_date_name: object, period_end: date) -> str:
    for raw in (report_type, report_date_name):
        if raw is None:
            continue
        text = str(raw)
        for key, code in _PERIOD_MAP.items():
            if key in text:
                return code
    return _period_from_date(period_end)


def _period_from_date(period_end: date) -> str:
    if (period_end.month, period_end.day) == (3, 31):
        return "Q1"
    if (period_end.month, period_end.day) == (6, 30):
        return "H1"
    if (period_end.month, period_end.day) == (9, 30):
        return "Q3"
    if (period_end.month, period_end.day) == (12, 31):
        return "FY"
    return "OTHER"


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _f(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


class FinancialNormalizer:
    """Map archived EM sheets → one row per (symbol, period_end, period_type)."""

    def normalize(self, batch: RawBatch, df: pl.DataFrame | None = None) -> pl.DataFrame:
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        if batch.source != "akshare":
            raise DataError(f"No financial normalizer for source={batch.source!r}")
        return self._normalize_akshare(frame, batch)

    def normalize_from_archive(self, raw_path: Path) -> pl.DataFrame:
        df, batch = load_raw_batch(raw_path)
        return self.normalize(batch, df)

    def _normalize_akshare(self, df: pl.DataFrame, batch: RawBatch) -> pl.DataFrame:
        if "_sheet" not in df.columns or "REPORT_DATE" not in df.columns:
            raise DataError("financial archive missing _sheet / REPORT_DATE")

        profit = self._pick(
            df,
            "profit",
            {
                "TOTAL_OPERATE_INCOME": "revenue",
                "OPERATE_COST": "operating_cost",
                "OPERATE_PROFIT": "operating_profit",
                "NETPROFIT": "net_profit",
                "PARENT_NETPROFIT": "net_profit_attr",
                "DEDUCT_PARENT_NETPROFIT": "net_profit_deducted",
                "BASIC_EPS": "eps",
            },
        )
        balance = self._pick(
            df,
            "balance",
            {
                "TOTAL_ASSETS": "total_assets",
                "TOTAL_LIABILITIES": "total_liab",
                "TOTAL_EQUITY": "total_equity",
                "TOTAL_PARENT_EQUITY": "equity_attr",
                "MONETARYFUNDS": "cash_and_equiv",
                "INVENTORY": "inventory",
                "ACCOUNTS_RECE": "accounts_recv",
                "GOODWILL": "goodwill",
            },
        )
        cashflow = self._pick(
            df,
            "cashflow",
            {
                "NETCASH_OPERATE": "cfo",
                "NETCASH_INVEST": "cfi",
                "NETCASH_FINANCE": "cff",
                "CONSTRUCT_LONG_ASSET": "capex",
            },
        )

        keys = ["_request_symbol", "REPORT_DATE", "REPORT_TYPE"]
        pieces = [p for p in (profit, balance, cashflow) if p.height]
        if not pieces:
            return pl.DataFrame(schema={c: pl.Null for c in CANONICAL_FIN_COLUMNS})

        joined = pieces[0]
        for other in pieces[1:]:
            joined = joined.join(other, on=keys, how="full", coalesce=True)

        meta = self._meta_frame(df)
        if meta.height:
            joined = joined.join(meta, on=keys, how="left")

        default_symbol = (batch.meta.get("symbols") or [None])[0]
        rows: list[dict[str, object]] = []
        for rec in joined.to_dicts():
            period_end = _to_date(rec.get("REPORT_DATE"))
            if period_end is None:
                continue
            announced = self._announced_at(rec)
            if announced is None:
                continue
            raw_sym = rec.get("_request_symbol")
            if raw_sym:
                symbol = normalize_symbol(str(raw_sym), market="CN")
            elif default_symbol:
                symbol = normalize_symbol(str(default_symbol), market="CN")
            else:
                continue

            revenue = _f(rec.get("revenue"))
            op_cost = _f(rec.get("operating_cost"))
            gross = (
                revenue - op_cost if revenue is not None and op_cost is not None else None
            )
            rows.append(
                {
                    "symbol": symbol,
                    "period_end": period_end,
                    "period_type": _map_period_type(
                        rec.get("REPORT_TYPE"),
                        rec.get("REPORT_DATE_NAME"),
                        period_end,
                    ),
                    "announced_at": announced,
                    "report_type": "original",
                    "revenue": revenue,
                    "operating_cost": op_cost,
                    "gross_profit": gross,
                    "operating_profit": _f(rec.get("operating_profit")),
                    "net_profit": _f(rec.get("net_profit")),
                    "net_profit_attr": _f(rec.get("net_profit_attr")),
                    "net_profit_deducted": _f(rec.get("net_profit_deducted")),
                    "eps": _f(rec.get("eps")),
                    "total_assets": _f(rec.get("total_assets")),
                    "total_liab": _f(rec.get("total_liab")),
                    "total_equity": _f(rec.get("total_equity")),
                    "equity_attr": _f(rec.get("equity_attr")),
                    "cash_and_equiv": _f(rec.get("cash_and_equiv")),
                    "inventory": _f(rec.get("inventory")),
                    "accounts_recv": _f(rec.get("accounts_recv")),
                    "goodwill": _f(rec.get("goodwill")),
                    "cfo": _f(rec.get("cfo")),
                    "cfi": _f(rec.get("cfi")),
                    "cff": _f(rec.get("cff")),
                    "capex": _f(rec.get("capex")),
                    "source": batch.source,
                }
            )

        if not rows:
            return pl.DataFrame(schema={c: pl.Null for c in CANONICAL_FIN_COLUMNS})
        return (
            pl.DataFrame(rows)
            .unique(
                subset=["symbol", "period_end", "period_type", "announced_at"],
                keep="first",
            )
            .select(CANONICAL_FIN_COLUMNS)
        )

    def _pick(
        self,
        df: pl.DataFrame,
        sheet: str,
        mapping: dict[str, str],
    ) -> pl.DataFrame:
        part = df.filter(pl.col("_sheet") == sheet)
        if part.height == 0:
            return pl.DataFrame()
        exprs = [
            pl.col("_request_symbol"),
            pl.col("REPORT_DATE"),
            pl.col("REPORT_TYPE"),
        ]
        for src, dst in mapping.items():
            if src in part.columns:
                exprs.append(pl.col(src).cast(pl.Float64, strict=False).alias(dst))
            else:
                exprs.append(pl.lit(None).cast(pl.Float64).alias(dst))
        return part.select(exprs)

    def _meta_frame(self, df: pl.DataFrame) -> pl.DataFrame:
        keys = ["_request_symbol", "REPORT_DATE", "REPORT_TYPE"]
        cols = keys + [
            c
            for c in ("NOTICE_DATE", "UPDATE_DATE", "REPORT_DATE_NAME")
            if c in df.columns
        ]
        return df.select(cols).unique(subset=keys, keep="first")

    @staticmethod
    def _announced_at(rec: dict[str, object]) -> datetime | None:
        # NOTICE_DATE = first public disclosure (PIT). UPDATE_DATE is often a
        # vendor refresh timestamp and can wrongly push visibility into the future.
        for key in ("NOTICE_DATE", "UPDATE_DATE"):
            d = _to_date(rec.get(key))
            if d is not None:
                return datetime.combine(d, time(15, 0), tzinfo=CN_TZ)
        return None
