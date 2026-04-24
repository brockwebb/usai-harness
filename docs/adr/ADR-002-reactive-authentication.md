# ADR-002: Reactive Authentication

**Status:** Accepted
**Date:** 2026-04-24

## Context

The harness authenticates to endpoints using API keys. These keys can expire, be revoked, or become invalid for reasons the harness cannot anticipate. The design question is when and how to detect these conditions.

One approach is to track key metadata in a local file: issue date, expected expiry, last-known-good timestamp. The harness checks freshness on startup and refuses to run if the key looks stale. This sounds defensive, but it introduces problems. Per-backend freshness semantics are needed, because Azure Key Vault rotates transparently while a file-based key does not. A state file must be gitignored, kept in sync, and reasoned about. Metadata can produce false positives when a key is refreshed out-of-band. Server-side revocation is not caught until the first call anyway.

The alternative is to treat the endpoint as the source of truth. The harness tries the call and handles authentication failures cleanly when they occur.

## Decision

Reactive authentication. The harness does not maintain key metadata files.

On HTTP 401 or 403, the worker pool halts, checkpoint state is preserved, and a clear error is raised instructing the user to refresh credentials. Rate-limit errors (HTTP 429) use a separate path covered in ADR-006.

A CLI subcommand `usai-harness ping` provides an optional cheap pre-flight check when a user wants verification before launching a long-running batch job.

## Consequences

Credential backends do not need freshness semantics. Each returns the current credential when asked, which simplifies the protocol defined in ADR-003.

The same authentication handling works across `.env` files, environment variables, Azure Key Vault, and any future backend.

A batch job started with a dead key fails on call one, not call five hundred. A job whose key expires mid-run fails cleanly at the moment of expiry. Checkpoint state is preserved in either case, so resume after refresh is straightforward.

Users running long jobs are advised in the README to verify key lifetime before starting, as an operational practice rather than a code-enforced check.
