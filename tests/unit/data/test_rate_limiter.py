"""Smoke test: RateLimiter spacing."""

from __future__ import annotations

import time

import pytest

from quantagent.data.collectors.base import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_enforces_interval() -> None:
    limiter = RateLimiter(0.05)
    t0 = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.045
