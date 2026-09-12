"""Unit tests for source degrade + fallback."""

from __future__ import annotations

import pytest

from quantagent.data.ops.degrade import try_collect_with_fallback
from quantagent.shared.errors import SourceUnavailableError


async def test_try_collect_primary_ok() -> None:
    async def primary() -> str:
        return "batch-a"

    async def fallback() -> str:
        return "batch-b"

    batch, degraded = await try_collect_with_fallback(
        primary,
        fallback,
        primary_source="akshare",
        fallback_source="baostock",
        dataset="price_daily",
    )
    assert batch == "batch-a"
    assert degraded is None


async def test_try_collect_fallback_on_unavailable() -> None:
    async def primary() -> str:
        raise SourceUnavailableError("akshare down")

    async def fallback() -> str:
        return "batch-b"

    batch, degraded = await try_collect_with_fallback(
        primary,
        fallback,
        primary_source="akshare",
        fallback_source="baostock",
        dataset="price_daily",
    )
    assert batch == "batch-b"
    assert degraded is not None
    assert "akshare down" in degraded.reason
    assert "price_daily" in degraded.annotation()


async def test_try_collect_reraises_when_both_fail() -> None:
    async def primary() -> str:
        raise SourceUnavailableError("primary down")

    async def fallback() -> str:
        raise SourceUnavailableError("fallback down")

    with pytest.raises(SourceUnavailableError, match="fallback down"):
        await try_collect_with_fallback(
            primary,
            fallback,
            primary_source="akshare",
            fallback_source="baostock",
            dataset="price_daily",
        )
