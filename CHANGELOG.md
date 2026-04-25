# Changelog

All notable changes to usai-harness are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-24

First release. Pip-installable Python client library for rate-limited, model-agnostic LLM calls against OpenAI-compatible endpoints, built for USAi and designed to work anywhere. 195 unit tests pass; the integration test against a live endpoint is staged but has not yet been executed against a live key.

### Added
- `USAiClient` main entry point in `client.py`. Wires together transport, rate limiter, worker pool, logger, and cost tracker.
- Pluggable transport layer (`transport.py`). Default backend uses `httpx`. `LiteLLMTransport` is stubbed for `pip install -e ".[litellm]"`.
- `CredentialProvider` protocol with three backends: `DotEnvProvider` (default), `EnvVarProvider` (CI/containers), `AzureKeyVaultProvider` (optional via `.[azure]`).
- `usai-harness` CLI dispatcher with seven subcommands: `init`, `add-provider`, `discover-models`, `verify`, `ping`, `cost-report`, `audit`.
- Live model catalog merge: the user-level catalog is authoritative at runtime. Models in seed config but absent from the live catalog are dropped per FR-040 / ADR-009; a WARN log line records dropped IDs and the catalog path so the failure mode is no longer silent.
- `redaction.py` module. Boundary-enforced scrubbing at `logger.log_call`, transport error bodies, and client exception handler. No global logging filter; emission boundaries call the scrubber explicitly.
- Token-bucket rate limiter (default 2.8 tokens/sec, burst 3). Adaptive backoff: 25% reduction on HTTP 429, 5% creep-up on success, floor 0.5/sec.
- Async worker pool (default 3 workers) with `AuthHaltError` for clean shutdown on 401/403.
- Append-only cost ledger (`cost_ledger.jsonl`). Records the rate applied at call time, allowing retroactive recomputation when rates change.
- Structured JSONL call logging with `model_requested` and `model_returned` fields. `report.generate_report` accepts older logs by mapping legacy `model` to `model_requested`.
- `usai-harness audit` command checks repo hygiene: gitignore coverage, tracked secrets, `pip-audit` integration.
- `ProviderConfig`: `api_key_env` names an environment variable for env-based backends; `api_key_secret` names a Key Vault secret for `azure_keyvault`. A provider declaring neither raises `ConfigError`.
- Integration test (`tests/integration/test_live_usai.py`) with 11 cases, including Test 11 for reactive auth (401/403 → `AuthHaltError`).
- `requirements.lock` hash-pinned for the core surface (`httpx`, `python-dotenv`, `pyyaml`). Optional extras (`.[azure]`, `.[litellm]`, `.[dev]`) are not hash-pinned per ADR-005.

### Deprecated
- `api_key_env` on `azure_keyvault` providers. Falling through to `api_key_env` for Azure emits a `DeprecationWarning` at config load. Removal target: 0.2.0. Migration: rename `api_key_env` to `api_key_secret` in `providers:` blocks for Azure backends.

### Security
- Error response bodies are redacted before logging.
- Non-HTTPS endpoints emit a TLS warning on first request.
- `model_requested` vs `model_returned` surfaces silent model substitution by the endpoint.

[Unreleased]: ../../compare/0.1.0...HEAD
[0.1.0]: ../../releases/tag/0.1.0
