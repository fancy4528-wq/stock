"""Write / read raw Collector responses as Parquet (+ sidecar meta)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from quantagent.data.contracts import RawBatch


def _batch_id_from_ts(ts: datetime) -> int:
    """Millisecond epoch used as a stable local batch id before ingest_batch table."""
    return int(ts.timestamp() * 1000)


class ParquetArchive:
    """Archive raw frames under ``data/raw/{source}/{dataset}/{target_date}/``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(
        self,
        *,
        source: str,
        dataset: str,
        target_date: date,
        collected_at: datetime | None = None,
    ) -> Path:
        ts = (collected_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        return self.root / source / dataset / target_date.isoformat() / f"{ts}.parquet"

    def write(
        self,
        df: pl.DataFrame,
        *,
        source: str,
        dataset: str,
        target_date: date,
        meta: dict[str, Any] | None = None,
        collected_at: datetime | None = None,
    ) -> RawBatch:
        collected = collected_at or datetime.now(UTC)
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=UTC)
        path = self.path_for(
            source=source,
            dataset=dataset,
            target_date=target_date,
            collected_at=collected,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)

        payload = {
            "source": source,
            "dataset": dataset,
            "target_date": target_date.isoformat(),
            "collected_at": collected.isoformat(),
            "row_count": df.height,
            "meta": meta or {},
        }
        path.with_suffix(".meta.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return RawBatch(
            batch_id=_batch_id_from_ts(collected),
            source=source,
            dataset=dataset,
            target_date=target_date,
            raw_path=path,
            row_count=df.height,
            collected_at=collected,
            meta=meta or {},
        )


def load_raw_batch(raw_path: Path) -> tuple[pl.DataFrame, RawBatch]:
    """Load an archived Parquet and its sidecar meta into a ``RawBatch``."""
    path = Path(raw_path)
    df = pl.read_parquet(path)
    meta_path = path.with_suffix(".meta.json")
    if meta_path.exists():
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        collected = datetime.fromisoformat(payload["collected_at"])
        target = date.fromisoformat(payload["target_date"]) if payload.get("target_date") else None
        batch = RawBatch(
            batch_id=_batch_id_from_ts(collected),
            source=payload["source"],
            dataset=payload["dataset"],
            target_date=target,
            raw_path=path,
            row_count=int(payload.get("row_count", df.height)),
            collected_at=collected,
            meta=dict(payload.get("meta") or {}),
        )
    else:
        collected = datetime.now(UTC)
        batch = RawBatch(
            batch_id=_batch_id_from_ts(collected),
            source="unknown",
            dataset="unknown",
            target_date=None,
            raw_path=path,
            row_count=df.height,
            collected_at=collected,
            meta={},
        )
    return df, batch
