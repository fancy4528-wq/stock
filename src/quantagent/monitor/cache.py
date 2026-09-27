"""L2 analysis result cache — content_hash + holdings_hash (P2b).

News is often syndicated across sources. Cache key includes holdings hash so
a position change invalidates prior relevance judgements.

Default backend: in-memory + optional JSON file (same pattern as suppression).
Does not import ``agents.llm`` — safe for zero-LLM call sites.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 86_400  # 24h — docs/16-token-economics.md
Direction = Literal["pos", "neg", "neu", ""]
Urgency = Literal["immediate", "today", "this_week", "low", ""]


class L2CachedTriage(BaseModel):
    """Persisted L2 row — no batch index ``i`` (reassigned on restore)."""

    rel: bool
    sym: list[str] = Field(default_factory=list)
    dir: Direction = ""
    urg: Urgency = ""
    deep: bool = False

    @field_validator("sym", mode="before")
    @classmethod
    def _norm_sym(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [str(x) for x in value if x]
        return []


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stores: int = 0
    expired_purged: int = 0


def holdings_hash(symbols: Iterable[str]) -> str:
    """Stable short hash of the holdings set (order-independent)."""
    cleaned = sorted({str(s).strip() for s in symbols if s and str(s).strip()})
    payload = "|".join(cleaned).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def l2_cache_key(content_hash: str, holdings: str) -> str:
    ch = (content_hash or "").strip()
    hh = (holdings or "").strip()
    if not ch or not hh:
        raise ValueError("content_hash and holdings_hash are required")
    return f"l2:{ch}:{hh}"


def resolve_content_hash(
    *,
    explicit: str | None,
    title: str,
    summary: str = "",
) -> str:
    """Prefer feed ``content_hash``; else hash title+summary (same idea as news normalizer)."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    payload = f"{(title or '').strip()}\n{(summary or '').strip()}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass
class AnalysisCache:
    """TTL cache for L2 triage results.

    Parameters
    ----------
    ttl_seconds:
        Entry lifetime (default 24h).
    path:
        Optional JSON persistence path (loaded on init, rewritten on set).
    """

    ttl_seconds: int = DEFAULT_TTL_SECONDS
    path: Path | None = None
    stats: CacheStats = field(default_factory=CacheStats)
    _store: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.path is not None:
            self.path = Path(self.path)
            self._load()

    def get(self, key: str, *, now: float | None = None) -> L2CachedTriage | None:
        ts = time.time() if now is None else now
        entry = self._store.get(key)
        if entry is None:
            self.stats.misses += 1
            return None
        expires_at, payload = entry
        if expires_at <= ts:
            self._store.pop(key, None)
            self.stats.misses += 1
            self.stats.expired_purged += 1
            return None
        try:
            self.stats.hits += 1
            return L2CachedTriage.model_validate(payload)
        except Exception:  # noqa: BLE001 — treat corrupt as miss
            self._store.pop(key, None)
            self.stats.misses += 1
            return None

    def set(self, key: str, value: L2CachedTriage, *, now: float | None = None) -> None:
        ts = time.time() if now is None else now
        self._store[key] = (ts + float(self.ttl_seconds), value.model_dump())
        self.stats.stores += 1
        self._save()

    def get_l2(
        self,
        content_hash: str,
        holdings: str,
        *,
        now: float | None = None,
    ) -> L2CachedTriage | None:
        try:
            key = l2_cache_key(content_hash, holdings)
        except ValueError:
            self.stats.misses += 1
            return None
        return self.get(key, now=now)

    def set_l2(
        self,
        content_hash: str,
        holdings: str,
        value: L2CachedTriage,
        *,
        now: float | None = None,
    ) -> None:
        key = l2_cache_key(content_hash, holdings)
        self.set(key, value, now=now)

    def purge_expired(self, *, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        dead = [k for k, (exp, _) in self._store.items() if exp <= ts]
        for k in dead:
            self._store.pop(k, None)
        self.stats.expired_purged += len(dead)
        if dead:
            self._save()
        return len(dead)

    def clear(self) -> None:
        self._store.clear()
        self._save()

    def __len__(self) -> int:
        return len(self._store)

    def _load(self) -> None:
        path = self.path
        if path is None or not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("analysis cache load failed (%s): %s", path, exc)
            return
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            return
        now = time.time()
        for key, item in entries.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                continue
            try:
                expires_at = float(item["expires_at"])
                value = item["value"]
            except (KeyError, TypeError, ValueError):
                continue
            if expires_at <= now or not isinstance(value, dict):
                continue
            self._store[key] = (expires_at, value)

    def _save(self) -> None:
        path = self.path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": {
                key: {"expires_at": exp, "value": value}
                for key, (exp, value) in self._store.items()
            }
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def default_cache_path(account: str = "manual_cn") -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "data" / "monitor" / f"analysis_cache_{account}.json"
    return Path("data/monitor") / f"analysis_cache_{account}.json"


def build_analysis_cache(
    *,
    account: str = "manual_cn",
    path: Path | str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    persist: bool = True,
) -> AnalysisCache:
    """Factory used by the monitor engine."""
    store_path: Path | None
    if path is not None:
        store_path = Path(path)
    elif persist:
        store_path = default_cache_path(account)
    else:
        store_path = None
    return AnalysisCache(ttl_seconds=ttl_seconds, path=store_path)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "AnalysisCache",
    "CacheStats",
    "L2CachedTriage",
    "build_analysis_cache",
    "default_cache_path",
    "holdings_hash",
    "l2_cache_key",
    "resolve_content_hash",
]
