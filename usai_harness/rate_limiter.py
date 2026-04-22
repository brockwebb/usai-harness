"""Rate Limiter: Token bucket with adaptive backoff.

Responsibilities:
    - Token bucket: 2.8 tokens/sec refill rate, burst capacity of 3
    - async acquire() blocks until a token is available
    - On HTTP 429: temporarily reduce refill rate, exponential creep back up
    - Track rolling average throughput (exponential moving average)
    - Thread-safe / async-safe: shared across all workers

Inputs:
    - refill_rate: float — tokens per second (default: 2.8)
    - burst: int — max tokens in bucket (default: 3)

Outputs:
    - acquire() — awaitable, returns when a token is available
    - record_429() — call on HTTP 429 to trigger adaptive reduction
    - stats() — returns current refill rate, bucket level, avg throughput
"""

import asyncio
import logging
import time

log = logging.getLogger("usai_harness.rate_limiter")

MIN_REFILL_RATE = 0.5
BACKOFF_FACTOR = 0.75
RECOVERY_FACTOR = 1.05
EMA_ALPHA = 0.1


class RateLimiter:
    """Token bucket rate limiter with adaptive backoff for USAi's 3/sec hard limit."""

    def __init__(self, refill_rate: float = 2.8, burst: int = 3):
        self._base_refill_rate = float(refill_rate)
        self._current_refill_rate = float(refill_rate)
        self._burst = float(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

        self._ema_throughput = 0.0
        self._last_acquire_time: float | None = None

        self._total_acquires = 0
        self._total_429s = 0

    async def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._burst,
                    self._tokens + elapsed * self._current_refill_rate,
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_acquires += 1
                    self._update_ema(now)
                    return

                deficit = 1.0 - self._tokens
                wait = deficit / self._current_refill_rate

            await asyncio.sleep(wait)

    def _update_ema(self, now: float) -> None:
        if self._last_acquire_time is not None:
            delta = now - self._last_acquire_time
            if delta > 0:
                sample = 1.0 / delta
                if self._ema_throughput == 0.0:
                    self._ema_throughput = sample
                else:
                    self._ema_throughput = (
                        EMA_ALPHA * sample
                        + (1.0 - EMA_ALPHA) * self._ema_throughput
                    )
        self._last_acquire_time = now

    def record_429(self) -> None:
        """Reduce the active refill rate by 25%, floored at MIN_REFILL_RATE."""
        old = self._current_refill_rate
        new = max(MIN_REFILL_RATE, old * BACKOFF_FACTOR)
        self._current_refill_rate = new
        self._total_429s += 1
        log.warning(
            "USAi 429 received; refill rate reduced %.3f -> %.3f tokens/sec.",
            old, new,
        )

    def record_success(self) -> None:
        """Creep the refill rate back toward base after a successful call."""
        if self._current_refill_rate < self._base_refill_rate:
            self._current_refill_rate = min(
                self._base_refill_rate,
                self._current_refill_rate * RECOVERY_FACTOR,
            )

    def stats(self) -> dict:
        return {
            "base_refill_rate": self._base_refill_rate,
            "current_refill_rate": self._current_refill_rate,
            "tokens_available": self._tokens,
            "avg_throughput": self._ema_throughput,
            "total_acquires": self._total_acquires,
            "total_429s": self._total_429s,
        }
