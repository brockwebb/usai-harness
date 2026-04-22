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
