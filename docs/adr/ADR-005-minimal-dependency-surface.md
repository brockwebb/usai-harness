# ADR-005: Minimal Dependency Surface

**Status:** Accepted
**Date:** 2026-04-24

## Context

The harness is distributed across federal environments with varying install restrictions. Every dependency is a potential install blocker. Every dependency is also a supply-chain surface that needs review.

Large dependency trees compound both problems. A package with fifty transitive dependencies is fifty accreditation questions, fifty audit surfaces, and fifty paths to a version conflict with whatever else the environment already has installed.

The harness should work in the most restrictive reasonable environment with no optional extras installed.

## Decision

Three hard dependencies:

1. `httpx` for async HTTP
2. `python-dotenv` for `.env` file loading
3. `pyyaml` for configuration parsing

All three are small, broadly audited, have minimal transitive dependencies, and are widely available across package repositories.

Additional functionality is delivered via optional extras:

- `.[litellm]` for the LiteLLM transport (ADR-001)
- `.[azure]` for Azure Key Vault credentials (ADR-003)
- `.[dev]` for test and development tooling

The core library works with no optional extras installed.

A hash-pinned lockfile at `requirements.lock` ships alongside `pyproject.toml`. Security-sensitive environments can install via `pip install -r requirements.lock --require-hashes` for reproducible, audited installs.

## Consequences

Installation works in restrictive environments that block large dependency trees.

Supply-chain review is tractable. Three packages, each with established provenance, is a reviewable set. Optional backends are reviewed separately and only where needed.

Some convenience features are not present out of the box: no built-in LLM abstraction, no retry library, no runtime schema validation beyond what's needed for config loading. These can be added per project or via optional extras. The cost of this minimalism is rewriting a small amount of logic that libraries like `tenacity` or `pydantic` provide. That cost is small compared to the benefit of install portability.
