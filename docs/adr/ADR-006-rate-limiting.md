# ADR-006: Rate Limiting via Token Bucket with Adaptive Backoff

**Status:** Accepted
**Date:** 2026-04-24

## Context

LLM providers enforce rate limits. USAi enforces 3 requests per second. Other endpoints (OpenRouter, Azure OpenAI, future providers) enforce different limits, sometimes much higher.

The harness must stay under each provider's limit while keeping throughput high. Hitting the limit produces HTTP 429 responses, which waste quota and add latency. Staying too far below the limit underuses the provider and makes batch jobs slower than they need to be.

Rate limits also fluctuate. A provider under load may tighten limits temporarily. A well-behaved client should notice and back off, then recover toward the configured rate when conditions allow.

## Decision

Token bucket rate limiter in `rate_limiter.py`. Default parameters for USAi:

- Refill rate: 2.8 tokens per second (safety margin below the 3/sec hard limit)
- Burst capacity: 3

Rate and burst are configurable per provider in `configs/models.yaml`.

Adaptive behavior:

- On HTTP 429, reduce the current refill rate by 25 percent.
- On sustained successful calls within a window, creep the refill rate back up by 5 percent.
- Floor at 0.5 tokens per second. Never go below.
- Ceiling at the configured rate. Never go above.

## Consequences

The harness does not sustainedly trip rate limits in steady state. The safety margin below 3/sec accounts for clock drift and server-side counting differences.

Brief provider-side rate reductions are absorbed without operator intervention. The adaptive algorithm recovers toward the configured rate when conditions allow.

Different providers get different bucket parameters via config. The same harness code handles USAi at 3/sec and OpenRouter at much higher rates without special casing.

The floor at 0.5/sec prevents runaway backoff during a sustained provider outage. The harness stays usable enough to complete a batch eventually, even if slowly.
