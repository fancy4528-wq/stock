"""Source-unavailable degrade + fallback collection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from quantagent.shared.errors import SourceUnavailableError

T = TypeVar("T")


@dataclass(frozen=True)
class DegradedSource:
    source: str
    dataset: str
    reason: str
    fallback: str

    def annotation(self) -> str:
        return (
            f"{self.dataset}: primary={self.source} unavailable ({self.reason}); "
            f"used fallback={self.fallback}"
        )


async def try_collect_with_fallback(
    primary_factory: Callable[[], Awaitable[T]],
    fallback_factory: Callable[[], Awaitable[T]],
    *,
    primary_source: str,
    fallback_source: str,
    dataset: str,
) -> tuple[T, DegradedSource | None]:
    """Try *primary_factory*; on ``SourceUnavailableError`` use *fallback_factory*."""
    try:
        return await primary_factory(), None
    except SourceUnavailableError as exc:
        reason = str(exc)
        try:
            batch = await fallback_factory()
        except SourceUnavailableError:
            raise
        degraded = DegradedSource(
            source=primary_source,
            dataset=dataset,
            reason=reason,
            fallback=fallback_source,
        )
        return batch, degraded
