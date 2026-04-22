"""Tests for token bucket, 429 adaptation, throughput tracking.

Uses fast refill rates (5-10/sec) so the suite finishes in a couple of seconds.
Timing assertions carry generous tolerances because async scheduling jitters.
"""

import asyncio
import time

import pytest

from usai_harness.rate_limiter import RateLimiter

pytestmark = pytest.mark.asyncio


async def test_burst_capacity():
    limiter = RateLimiter(refill_rate=2.8, burst=3)
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"burst of 3 should be instantaneous, took {elapsed:.3f}s"


async def test_blocks_when_empty():
    limiter = RateLimiter(refill_rate=10, burst=1)
    await limiter.acquire()  # consume the burst token

    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start

    assert 0.05 <= elapsed <= 0.15, (
        f"second acquire should wait ~0.1s at rate=10, got {elapsed:.3f}s"
    )


async def test_refill_rate_respected():
    limiter = RateLimiter(refill_rate=5, burst=1)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start

    assert 0.6 <= elapsed <= 1.0, (
        f"5 acquires at rate=5 (burst=1) should take ~0.8s, got {elapsed:.3f}s"
    )


async def test_429_reduces_rate():
    limiter = RateLimiter(refill_rate=2.8, burst=3)
    limiter.record_429()
    assert limiter.stats()["current_refill_rate"] == pytest.approx(2.8 * 0.75, abs=1e-6)


async def test_429_floor():
    limiter = RateLimiter(refill_rate=2.8, burst=3)
    for _ in range(10):
        limiter.record_429()
    assert limiter.stats()["current_refill_rate"] >= 0.5


async def test_success_recovery():
    limiter = RateLimiter(refill_rate=2.8, burst=3)
    limiter.record_429()
    reduced = limiter.stats()["current_refill_rate"]

    for _ in range(20):
        limiter.record_success()
    recovered = limiter.stats()["current_refill_rate"]

    assert recovered > reduced, "successive record_success() should raise the rate"
    assert recovered <= 2.8 + 1e-9, "rate must not exceed configured base"


async def test_stats_counts():
    limiter = RateLimiter(refill_rate=10, burst=5)
    for _ in range(5):
        await limiter.acquire()
    limiter.record_429()
    limiter.record_429()

    stats = limiter.stats()
    assert stats["total_acquires"] == 5
    assert stats["total_429s"] == 2


async def test_concurrent_acquire():
    limiter = RateLimiter(refill_rate=2.8, burst=3)
    start = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(6)))
    elapsed = time.monotonic() - start

    # 3 immediate + 3 more at ~0.357s each = ~1.07s
    assert 0.6 <= elapsed <= 1.6, (
        f"6 concurrent acquires at rate=2.8 should take ~1.07s, got {elapsed:.3f}s"
    )
    assert limiter.stats()["total_acquires"] == 6
