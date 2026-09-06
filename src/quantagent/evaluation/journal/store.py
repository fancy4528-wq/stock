"""Append-only decision / shadow journal (file-backed for P1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quantagent.shared.errors import JournalMutationError


class AppendOnlyJournal:
    """JSONL store. Only append + read; update/delete raise."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, record: BaseModel | dict[str, Any]) -> None:
        payload = record.model_dump(mode="json") if isinstance(record, BaseModel) else record
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def update(self, *_args: Any, **_kwargs: Any) -> None:
        raise JournalMutationError(f"journal is append-only: {self.path}")

    def delete(self, *_args: Any, **_kwargs: Any) -> None:
        raise JournalMutationError(f"journal is append-only: {self.path}")
