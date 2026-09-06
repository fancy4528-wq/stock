"""Normalize Shenwan industry raw frames to canonical taxonomy + memberships."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.collectors.akshare.industry import sw_code_digits
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.errors import DataError

__all__ = [
    "CANONICAL_INDUSTRY_COLUMNS",
    "CANONICAL_MEMBERSHIP_COLUMNS",
    "IndustryNormalizer",
    "SW2021_EFFECTIVE",
]

# Shenwan 2021 industry classification effective date (common backfill anchor).
SW2021_EFFECTIVE = date(2021, 12, 13)

CANONICAL_INDUSTRY_COLUMNS = [
    "record_type",
    "taxonomy_code",
    "industry_code",
    "industry_name",
    "level",
    "parent_code",
    "source",
]

CANONICAL_MEMBERSHIP_COLUMNS = [
    "record_type",
    "taxonomy_code",
    "symbol",
    "industry_code",
    "industry_name",
    "level",
    "valid_from",
    "valid_to",
    "source",
]


class IndustryNormalizer:
    """Map akshare SW frames → ``industry`` + ``security_industry`` load rows."""

    def normalize(self, batch: RawBatch, df: pl.DataFrame | None = None) -> pl.DataFrame:
        if batch.source != "akshare":
            raise DataError(f"No industry normalizer for source={batch.source!r}")
        frame = df if df is not None else pl.read_parquet(batch.raw_path)
        if frame.is_empty() or "_kind" not in frame.columns:
            raise DataError("industry raw frame missing _kind")

        taxonomy_code = str(batch.meta.get("taxonomy") or "sw_2021")
        industries = self._normalize_taxonomy(frame, taxonomy_code=taxonomy_code)
        memberships = self._normalize_memberships(
            frame,
            industries=industries,
            taxonomy_code=taxonomy_code,
            filter_symbols=batch.meta.get("filter_symbols"),
        )
        if industries.is_empty() and memberships.is_empty():
            raise DataError("industry normalize produced empty frame")
        return pl.concat([industries, memberships], how="diagonal_relaxed")

    def normalize_from_archive(self, raw_path: Path) -> pl.DataFrame:
        df, batch = load_raw_batch(raw_path)
        return self.normalize(batch, df)

    def _normalize_taxonomy(self, df: pl.DataFrame, *, taxonomy_code: str) -> pl.DataFrame:
        parts: list[pl.DataFrame] = []
        name_to_code: dict[str, str] = {}

        for level, kind in ((1, "taxonomy_l1"), (2, "taxonomy_l2"), (3, "taxonomy_l3")):
            part = df.filter(pl.col("_kind") == kind)
            if part.is_empty():
                continue
            if "行业代码" not in part.columns or "行业名称" not in part.columns:
                raise DataError(f"{kind} missing 行业代码/行业名称")

            rows: list[dict[str, object]] = []
            for rec in part.to_dicts():
                code = sw_code_digits(str(rec["行业代码"]))
                name = str(rec["行业名称"]).strip()
                parent_code: str | None = None
                if level > 1:
                    parent_name = rec.get("上级行业")
                    if parent_name is not None and str(parent_name).strip():
                        parent_code = name_to_code.get(str(parent_name).strip())
                name_to_code[name] = code
                rows.append(
                    {
                        "record_type": "industry",
                        "taxonomy_code": taxonomy_code,
                        "industry_code": code,
                        "industry_name": name,
                        "level": level,
                        "parent_code": parent_code,
                        "source": "akshare",
                    }
                )
            parts.append(pl.DataFrame(rows))

        if not parts:
            return pl.DataFrame(
                {
                    "record_type": pl.Series([], dtype=pl.Utf8),
                    "taxonomy_code": pl.Series([], dtype=pl.Utf8),
                    "industry_code": pl.Series([], dtype=pl.Utf8),
                    "industry_name": pl.Series([], dtype=pl.Utf8),
                    "level": pl.Series([], dtype=pl.Int64),
                    "parent_code": pl.Series([], dtype=pl.Utf8),
                    "source": pl.Series([], dtype=pl.Utf8),
                }
            )
        return pl.concat(parts, how="diagonal_relaxed").select(CANONICAL_INDUSTRY_COLUMNS)

    def _normalize_memberships(
        self,
        df: pl.DataFrame,
        *,
        industries: pl.DataFrame,
        taxonomy_code: str,
        filter_symbols: list[str] | None,
    ) -> pl.DataFrame:
        empty = pl.DataFrame(
            {
                "record_type": pl.Series([], dtype=pl.Utf8),
                "taxonomy_code": pl.Series([], dtype=pl.Utf8),
                "symbol": pl.Series([], dtype=pl.Utf8),
                "industry_code": pl.Series([], dtype=pl.Utf8),
                "industry_name": pl.Series([], dtype=pl.Utf8),
                "level": pl.Series([], dtype=pl.Int64),
                "valid_from": pl.Series([], dtype=pl.Date),
                "valid_to": pl.Series([], dtype=pl.Date),
                "source": pl.Series([], dtype=pl.Utf8),
            }
        )
        members = df.filter(pl.col("_kind") == "member_l1")
        if members.is_empty():
            return empty

        if "证券代码" not in members.columns or "_industry_code" not in members.columns:
            raise DataError("member_l1 missing 证券代码 / _industry_code")

        name_by_code: dict[str, str] = {}
        if not industries.is_empty():
            for rec in industries.filter(pl.col("level") == 1).to_dicts():
                name_by_code[str(rec["industry_code"])] = str(rec["industry_name"])

        allow = set(filter_symbols) if filter_symbols else None
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for rec in members.to_dicts():
            raw_sym = rec.get("证券代码")
            if raw_sym is None:
                continue
            try:
                symbol = normalize_symbol(str(raw_sym), market="CN")
            except ValueError:
                continue
            if allow is not None and symbol not in allow:
                continue
            if symbol in seen:
                continue
            seen.add(symbol)

            ind_code = sw_code_digits(str(rec["_industry_code"]))
            valid_from = SW2021_EFFECTIVE
            if "计入日期" in members.columns and rec.get("计入日期") is not None:
                parsed = _parse_date(rec["计入日期"])
                if parsed is not None:
                    valid_from = parsed

            rows.append(
                {
                    "record_type": "membership",
                    "taxonomy_code": taxonomy_code,
                    "symbol": symbol,
                    "industry_code": ind_code,
                    "industry_name": name_by_code.get(ind_code, ind_code),
                    "level": 1,
                    "valid_from": valid_from,
                    "valid_to": None,
                    "source": "akshare",
                }
            )

        if not rows:
            return empty
        return pl.DataFrame(rows).select(CANONICAL_MEMBERSHIP_COLUMNS)


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    if " " in text:
        text = text.split(" ", 1)[0]
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
