"""Load curated K2 periodic-report packs (MD&A / risk text) from disk."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from quantagent.data.collectors.base import Collector, RawBatch
from quantagent.shared.errors import DataError

__all__ = [
    "ReportPackCollector",
    "default_fixture_pack_path",
    "load_report_packs",
    "packs_to_dataframe",
]

_REQUIRED = ("symbol", "fiscal_year", "disclose_date")


def default_fixture_pack_path() -> Path:
    """Built-in fixture pack used by ``make ingest-reports`` / unit tests."""
    # pack.py → reports → collectors → data → quantagent → src → <repo>
    return (
        Path(__file__).resolve().parents[5]
        / "tests"
        / "fixtures"
        / "reports"
        / "k2_packs.jsonl"
    )


def load_report_packs(path: Path) -> list[dict[str, Any]]:
    """Load JSONL or JSON-array report packs from ``path``."""
    if not path.exists():
        raise DataError(f"report pack file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    rows: list[dict[str, Any]]
    if path.suffix.lower() == ".jsonl" or "\n" in text and text.lstrip().startswith("{"):
        rows = []
        for i, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataError(f"invalid JSONL at {path}:{i}: {exc}") from exc
            if not isinstance(obj, dict):
                raise DataError(f"report pack line {i} must be an object")
            rows.append(obj)
    else:
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows = [payload]
        elif isinstance(payload, list):
            rows = []
            for i, obj in enumerate(payload, start=1):
                if not isinstance(obj, dict):
                    raise DataError(f"report pack item {i} must be an object")
                rows.append(obj)
        else:
            raise DataError("report pack JSON must be object or array")
    return [_validate_pack(r, index=i) for i, r in enumerate(rows, start=1)]


def packs_to_dataframe(packs: list[dict[str, Any]]) -> pl.DataFrame:
    """Flatten packs into a Polars frame suitable for ParquetArchive."""
    if not packs:
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "fiscal_year": pl.Int64,
                "report_kind": pl.Utf8,
                "disclose_date": pl.Utf8,
                "period_end": pl.Utf8,
                "title": pl.Utf8,
                "mda_text": pl.Utf8,
                "risk_text": pl.Utf8,
                "full_text": pl.Utf8,
            }
        )
    flat: list[dict[str, Any]] = []
    for p in packs:
        flat.append(
            {
                "symbol": str(p["symbol"]),
                "fiscal_year": int(p["fiscal_year"]),
                "report_kind": str(p.get("report_kind") or "annual"),
                "disclose_date": _iso_date(p["disclose_date"]),
                "period_end": _iso_date(p["period_end"]) if p.get("period_end") else None,
                "title": str(p.get("title") or ""),
                "mda_text": str(p.get("mda_text") or ""),
                "risk_text": str(p.get("risk_text") or ""),
                "full_text": str(p.get("full_text") or ""),
            }
        )
    return pl.DataFrame(flat)


def _iso_date(raw: object) -> str:
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    return str(raw)[:10]


def _validate_pack(pack: dict[str, Any], *, index: int) -> dict[str, Any]:
    for key in _REQUIRED:
        if key not in pack or pack[key] in (None, ""):
            raise DataError(f"report pack #{index} missing required field {key!r}")
    has_body = any(
        str(pack.get(k) or "").strip() for k in ("mda_text", "risk_text", "full_text")
    )
    if not has_body:
        raise DataError(
            f"report pack #{index} needs mda_text, risk_text, or full_text"
        )
    return pack


class ReportPackCollector(Collector):
    """Archive curated report packs (no network). Dataset ``report_pack``."""

    source = "report_pack"
    dataset = "periodic_report"
    rate_limit = 0.0

    def __init__(
        self,
        archive_root: Path | None = None,
        *,
        pack_path: Path | None = None,
    ) -> None:
        super().__init__(archive_root=archive_root)
        self._pack_path = pack_path or default_fixture_pack_path()

    async def collect(self, target_date: date, **kwargs: Any) -> RawBatch:
        path = kwargs.get("pack_path") or self._pack_path
        if not isinstance(path, Path):
            path = Path(str(path))
        packs = load_report_packs(path)
        df = packs_to_dataframe(packs)
        return self._archive.write(
            df,
            source=self.source,
            dataset=self.dataset,
            target_date=target_date,
            meta={
                "interface": "local_report_pack",
                "pack_path": str(path.resolve()),
                "rows": df.height,
                "note": "K2 MD&A/risk text packs; visible_at = disclose_date",
            },
            collected_at=self._now(),
        )
