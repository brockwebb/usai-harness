# ADR-001: Pluggable Transport Layer

**Status:** Accepted
**Date:** 2026-04-24

## Context

The harness needs to call OpenAI-compatible LLM endpoints. Several libraries abstract this kind of call, and LiteLLM is the leading option. We evaluated LiteLLM on ownership, customer base (which includes NASA), license, and engineering quality. The evaluation came back clean.

Adoption is a separate question from evaluation. Federal environments vary widely in what packages and package versions are permitted. Each authorization-to-operate (ATO) boundary imposes its own constraints. Some environments run versions of common packages that lag upstream by months or years. Some lack a given package entirely. A harness that hard-depends on LiteLLM works on a developer laptop and fails the first time it crosses into a locked-down environment. That pattern recurs often enough to treat as a design constraint.

## Decision

Define a thin transport contract in `transport.py`. Any backend that satisfies the contract can be used. Ship two concrete transports:

1. `HttpxTransport` as the default. Depends only on `httpx`. Makes direct HTTP calls to any OpenAI-compatible endpoint. No LLM framework dependencies.
2. `LiteLLMTransport` as an optional backend, installed via `pip install -e ".[litellm]"`. Preferred where the environment permits a current LiteLLM version.

The active transport is selected per project via configuration. Adding a new backend does not require changes to `client.py`, `worker_pool.py`, `rate_limiter.py`, or any other module.

## Consequences

Core installation works in any Python 3.12+ environment that allows three small, widely audited dependencies: `httpx`, `python-dotenv`, `pyyaml`. The harness functions where LiteLLM cannot be installed.

LiteLLM remains the preferred abstraction where available. Projects in environments with a current LiteLLM version gain its multi-provider features, streaming support, and broader model catalog without giving up portability elsewhere.

Organizations running forks or newer LiteLLM releases can extend the transport layer without modifying the rest of the harness.

The cost of this design is one extra interface layer and some error-handling logic that repeats across transports. That cost is small compared to the cost of being locked out of a target environment by a dependency.
