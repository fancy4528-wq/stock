"""Normalize CLS / EM flash + EM announcements → canonical ``news`` rows."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantagent.data.archive.parquet import load_raw_batch
from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.symbol import normalize_symbol
from quantagent.shared.errors import DataError

CN_TZ = ZoneInfo("Asia/Shanghai")

CANONICAL_NEWS_COLUMNS = [
    "source",
    "source_id",
    "url",
    "title",
    "body",
    "published_at",
    "lang",
    "content_hash",
    "raw_ref",
    "related_symbol",  # optional; stored on news for extract hints
    "announce_type",  # optional hint for rule extractor
]

_EM_URL_ID = re.compile(r"/a/(\d+)\.html", re.IGNORECASE)
_ANNOUNCE_ID = re.compile(r"/(AN\d+)\.html", re.IGNORECASE)
_ANNOUNCE_URL_CODE = re.compile(
    r"/notices/detail/(?P<code>\d{6})/",
    re.IGNORECASE,
)


def content_hash(title: str, body: str | None) -> str:
    payload = f"{title.strip()}\n{(body or '').strip()}".encode()
    return hashlib.sha256(payload).hexdigest()


def symbol_from_em_announce_url(url: str | None) -> str | None:
    """Recover CN ticker from East Money notice detail URL when present."""
    if not url:
        return None
    m = _ANNOUNCE_URL_CODE.search(str(url))
    if not m:
        return None
    return _safe_symbol(m.group("code"))


def _parse_cls_published(row: dict[str, object]) -> datetime:
    d_raw = row.get("发布日期")
    t_raw = row.get("发布时间")
    if d_raw is None:
        raise DataError("CLS row missing 发布日期")
    day = date.fromisoformat(str(d_raw)[:10])
    if t_raw is None or str(t_raw).strip() == "":
        return datetime.combine(day, time(0, 0), tzinfo=CN_TZ)
    parts = str(t_raw).strip().split(":")
    hh = int(parts[0]) if len(parts) > 0 else 0
    mm = int(parts[1]) if len(parts) > 1 else 0
    ss = int(parts[2]) if len(parts) > 2 else 0
    return datetime.combine(day, time(hh, mm, ss), tzinfo=CN_TZ)


def _parse_em_published(raw: object) -> datetime:
    text = str(raw).strip()
    if not text:
        raise DataError("EM row missing 发布时间")
    # "2026-09-13 12:42:33"
    if " " in text:
        d_part, t_part = text.split(" ", 1)
        day = date.fromisoformat(d_part[:10])
        parts = t_part.split(":")
        hh = int(parts[0]) if parts else 0
        mm = int(parts[1]) if len(parts) > 1 else 0
        ss = int(float(parts[2])) if len(parts) > 2 else 0
        return datetime.combine(day, time(hh, mm, ss), tzinfo=CN_TZ)
    day = date.fromisoformat(text[:10])
    return datetime.combine(day, time(0, 0), tzinfo=CN_TZ)


def _em_source_id(url: str | None, title: str, body: str | None) -> str:
    if url:
        m = _EM_URL_ID.search(url)
        if m:
            return m.group(1)
    return content_hash(title, body)[:32]


def _announce_source_id(url: str | None, code: str, title: str) -> str:
    if url:
        m = _ANNOUNCE_ID.search(url)
        if m:
            return m.group(1)
    return content_hash(f"{code}:{title}", None)[:32]


def _safe_symbol(code: object) -> str | None:
    if code is None:
        return None
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if len(digits) != 6:
        return None
    try:
        return normalize_symbol(digits, market="CN")
    except ValueError:
        return None


class NewsNormalizer:
    """Map vendor flash / notice frames to canonical news columns."""

    def normalize(self, batch: RawBatch) -> pl.DataFrame:
        df = pl.read_parquet(batch.raw_path)
        return self._normalize_frame(
            df,
            source=batch.source,
            dataset=batch.dataset,
            raw_ref=str(batch.raw_path),
        )

    def normalize_from_archive(self, raw_path: Path | str) -> pl.DataFrame:
        df, batch = load_raw_batch(Path(raw_path))
        return self._normalize_frame(
            df,
            source=batch.source,
            dataset=batch.dataset,
            raw_ref=str(batch.raw_path),
        )

    def _normalize_frame(
        self,
        df: pl.DataFrame,
        *,
        source: str,
        dataset: str,
        raw_ref: str,
    ) -> pl.DataFrame:
        if df.is_empty():
            return pl.DataFrame(schema={c: pl.Utf8 for c in CANONICAL_NEWS_COLUMNS})

        if source == "cls" or (dataset == "news" and "内容" in df.columns):
            rows = self._from_cls(df, raw_ref=raw_ref)
        elif source == "em" or (dataset == "news" and "摘要" in df.columns):
            rows = self._from_em(df, raw_ref=raw_ref)
        elif source == "em_announce" or dataset == "announcement":
            rows = self._from_announce(df, raw_ref=raw_ref)
        else:
            raise DataError(f"NewsNormalizer unsupported source={source!r} dataset={dataset!r}")

        if not rows:
            return pl.DataFrame(schema={c: pl.Utf8 for c in CANONICAL_NEWS_COLUMNS})

        out = pl.DataFrame(rows)
        # Dedupe within batch by (source, content_hash)
        return out.unique(subset=["source", "content_hash"], keep="first")

    def _from_cls(self, df: pl.DataFrame, *, raw_ref: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in df.to_dicts():
            title = str(row.get("标题") or "").strip()
            if not title:
                continue
            body = str(row.get("内容") or "").strip() or None
            published = _parse_cls_published(row)
            ch = content_hash(title, body)
            sid = content_hash(f"{published.isoformat()}|{title}", body)[:32]
            rows.append(
                {
                    "source": "cls",
                    "source_id": sid,
                    "url": None,
                    "title": title,
                    "body": body,
                    "published_at": published,
                    "lang": "zh",
                    "content_hash": ch,
                    "raw_ref": raw_ref,
                    "related_symbol": None,
                    "announce_type": None,
                }
            )
        return rows

    def _from_em(self, df: pl.DataFrame, *, raw_ref: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in df.to_dicts():
            title = str(row.get("标题") or "").strip()
            if not title:
                continue
            body = str(row.get("摘要") or "").strip() or None
            url = str(row.get("链接") or "").strip() or None
            published = _parse_em_published(row.get("发布时间"))
            ch = content_hash(title, body)
            rows.append(
                {
                    "source": "em",
                    "source_id": _em_source_id(url, title, body),
                    "url": url,
                    "title": title,
                    "body": body,
                    "published_at": published,
                    "lang": "zh",
                    "content_hash": ch,
                    "raw_ref": raw_ref,
                    "related_symbol": None,
                    "announce_type": None,
                }
            )
        return rows

    def _from_announce(self, df: pl.DataFrame, *, raw_ref: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in df.to_dicts():
            title = str(row.get("公告标题") or "").strip()
            if not title:
                continue
            code = row.get("代码")
            url = str(row.get("网址") or "").strip() or None
            announce_type = str(row.get("公告类型") or "").strip() or None
            d_raw = row.get("公告日期")
            if d_raw is None:
                continue
            day = date.fromisoformat(str(d_raw)[:10])
            published = datetime.combine(day, time(16, 0), tzinfo=CN_TZ)
            name = str(row.get("名称") or "").strip()
            symbol = _safe_symbol(code)
            # Keep ticker in body so regex extract still works if hint is dropped.
            body = " ".join(
                p for p in (symbol or "", announce_type or "", name, title) if p
            ).strip()
            ch = content_hash(title, body)
            rows.append(
                {
                    "source": "em_announce",
                    "source_id": _announce_source_id(url, str(code or ""), title),
                    "url": url,
                    "title": title,
                    "body": body,
                    "published_at": published,
                    "lang": "zh",
                    "content_hash": ch,
                    "raw_ref": raw_ref,
                    "related_symbol": symbol,
                    "announce_type": announce_type,
                }
            )
        return rows
