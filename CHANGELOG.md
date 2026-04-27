# Changelog

All notable changes to usai-harness are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI workflow at `.github/workflows/ci.yml`. Test matrix across Linux, macOS, and Windows on Python 3.12, 3.13, and 3.14. Separate jobs for `pip-audit` (advisory, soft-fail with findings surfaced to the job summary) and lockfile-install verification (`pip install --require-hashes -r requirements.lock` plus a hard-deps-only smoke test).
- Dependabot configuration at `.github/dependabot.yml` for weekly pip and github-actions dependency update PRs.
- `error_body` field on failed-call log entries. Captures up to `error_body_snippet_max_chars` (default 200, range 1-2000) of the response body on non-2xx responses, passed through `redact_secrets()` before write. Skipped for binary content types and on body-read failure. Surfaces endpoint-side rejection reasons such as Gemini's "API key not valid" message that were previously lost.
- `error_body_snippet_max_chars` top-level configuration setting in `configs/models.yaml` and project config, validated at load.
- `tests/conftest.py` autouse fixture that redirects user-level config paths into a per-test tmp directory. Eliminates leakage of populated user-level catalogs into config tests.
- `SECURITY.md` vulnerability disclosure policy at repo root. GitHub private vulnerability reporting as primary channel, security-only email fallback, ninety-day default coordination window, scope and non-scope explicit.
- Operations guide section 7 "Provider-specific behavior" documenting four observed divergences between USAi and Gemini: auth-failure status code (401/403 vs 400), Gemini 2.5 thinking-token budget interaction with `max_tokens`, model ID prefix (`models/...`), and interactive-only `add-provider`.
- README caveat referring readers to ops-guide section 7 for known endpoint divergences.
- SRS FR-042 (authoritative drop warning is a documented requirement, not just an implementation detail).
- SRS IR-005 (`error_body_snippet_max_chars` is a config schema element).
- API reference Section 4.2 documents the `api_key_env` vs `api_key_secret` split.
- API reference Section 5.1 shows a failed-call example with `error_body`.
- API reference Section 6 cross-references the per-provider auth-failure divergence.

### Removed
- `api_key_env` fallback on `azure_keyvault` credential providers. Use `api_key_secret` instead. Previously emitted a `DeprecationWarning`; now raises `ConfigError`.

### Changed
- Engineering documentation spine (`docs/srs.md`, `docs/rtm.md`, `docs/nfr.md`, `docs/architecture.md`, `docs/tevv-plan.md`) brought current with the alignment sweep and Tasks 06 through 10. RTM Section 8 repurposed from baseline-gaps to current-remaining-work; coverage summary recomputed after FR-042 and IR-005 additions.
- ADR-007 amended to document the reversal of the original Task 04 conservative decision to drop error response bodies. Boundary-enforced redaction validated by Task 08 Gemini smoke test now makes diagnostic body capture safe.
- `transport.py` module docstring documents the rationale for error body snippet capture and warns future contributors against reverting it.
- Test count: 208 unit tests (was 195 at 0.1.0).

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
