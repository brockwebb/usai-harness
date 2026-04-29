# Changelog

All notable changes to usai-harness are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New CLI subcommand `usai-harness list-models` prints the merged catalog (repo + user-level). Supports `--provider` filtering and `--format {table,yaml,names}` output. Useful for finding exact model names to declare in `usai_harness.yaml` pool configs.

### Removed
- Per-model parameter validation (`temperature_range`, `max_output_tokens`) from `ProjectConfig` and the model catalog. The harness no longer enforces parameter ranges; provider response is the source of truth. (ADR-012 amendment, 2026-04-29)

### Changed
- Catalog schema (`configs/models.yaml` and user-level catalog): `temperature_range` and `max_output_tokens` fields removed. Catalog entries describe identity and accounting only.
- ProjectConfig pool members forward all per-model fields (recognized or not) to the transport unchanged.

## [0.2.0] - 2026-04-28

The 0.2.0 release lands three architectural changes recorded in ADRs 011, 012, and 013, all aimed at making the harness adoption-ready for downstream projects. A new project carries its own `usai_harness.yaml` at project root (ADR-011), declares a pool of models rather than a single model (ADR-012), and bootstraps in one command with a TEVV smoke test that produces a markdown provenance report (ADR-013). The federal-survey-concept-mapper integration is the forcing function: every change in this release came from a real consumer hitting a real friction point during adoption.

### Added
- New CLI subcommand `usai-harness project-init` that creates a standard project layout (`usai_harness.yaml`, `output/`, `output/logs/`, `tevv/`, `scripts/example_batch.py`) and runs a TEVV smoke round-trip against the project's default model (ADR-013). Idempotent: re-running leaves the config and example script in place, deduplicates `.gitignore` entries, and writes a fresh timestamped report under `tevv/`.
- Templates directory `usai_harness/templates/` with starter project config and example script, packaged via `pyproject.toml [tool.setuptools.package-data]`.
- TEVV report format: markdown reports written to `tevv/init_report_<UTC_timestamp>.md` capture harness version, Python and OS, project root, provider, default model, full pool, prompt, status code, latency, token counts, total cost, response sample, and a PASS/FAIL verdict (IR-006).
- `ProjectConfig` now declares a pool of models via the `models:` list field, plus a `default_model:` field selecting which pool member is used when a task does not specify (ADR-012). A new top-level `provider:` field is required when pool members come from multiple providers; cross-provider pools are rejected. Per-model `temperature` and `max_tokens` overrides validate against that member's catalog ranges, not the default model's.
- `USAiClient` discovers `usai_harness.yaml` in the current working directory by default (ADR-011). An explicit `config_path=` continues to override the discovery rule. When neither is present, the client falls back to the catalog's default model with default `ProjectConfig` values.
- New `ProjectConfig` helpers: `has_model(name)` and `get_pool_model(name)`.

### Changed
- `client.complete()` and `client.batch()` now validate per-call/per-task `model` and `temperature` overrides against the chosen pool member at call/task-build time. Tasks targeting a non-pool model raise `ValueError`; out-of-range temperatures raise with the offending value, model name, and valid range.
- The legacy single-`model:` form in project configs is silently translated to a one-element pool. Configs declaring both `model:` and `models:` raise `ConfigValidationError`.

## [0.1.1] - 2026-04-27

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

### Fixed
- `usai-harness init` no longer hard-fails when the endpoint's `/models` response is unavailable (404, timeout, connection error). It warns, prompts the user for a default model ID, writes credentials regardless, and exits 0. Test completion failure also no longer blocks credential write; the warning is informational. Resolves the showstopper where a partly-working endpoint left first-time users with no configured credentials.
- `usai-harness discover-models` exits 0 on partial provider failure (with a stderr warning naming the failing providers) instead of 3, so a single bad endpoint does not abort batch refresh of the others.
- `usai-harness ping` accepts `--model` so you can target a specific model when the user-level catalog is empty (typical right after a first-run `init` against an endpoint with discovery offline).

### Changed
- `usai-harness init` now auto-detects the API path prefix during setup. After the user enters a base URL, the harness probes `/api/v1`, then `/v1`, then the bare URL against the endpoint's `/models`; the first 200 wins and the resolved URL (with prefix) is stored. Users who paste a bare hostname (the same URL they'd paste into the API tester) get a working setup without needing to know `/api/v1` vs `/v1`. Users who already include a prefix are unaffected. If every probe fails, the Task 15 fallback path (warn, prompt for default model, save credentials anyway) still applies.
- `usai-harness init` and `usai-harness add-provider` now show masked echo (`*` per character) when entering an API key, instead of the silent `getpass` prompt that left users unsure whether their paste landed. After capture, a one-line confirmation prints the key as `****<last4>` so the paste can be visually verified. The masked-input helper uses `msvcrt` on Windows and `termios`/`tty` on Linux/macOS, with a non-interactive fallback for piped stdin.
- Engineering documentation spine (`docs/srs.md`, `docs/rtm.md`, `docs/nfr.md`, `docs/architecture.md`, `docs/tevv-plan.md`) brought current with the alignment sweep and Tasks 06 through 10. RTM Section 8 repurposed from baseline-gaps to current-remaining-work; coverage summary recomputed after FR-042 and IR-005 additions.
- ADR-007 amended to document the reversal of the original Task 04 conservative decision to drop error response bodies. Boundary-enforced redaction validated by Task 08 Gemini smoke test now makes diagnostic body capture safe.
- `transport.py` module docstring documents the rationale for error body snippet capture and warns future contributors against reverting it.
- Test count: 213 unit tests (was 195 at 0.1.0). All 11 integration tests pass against live USAi.

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

[Unreleased]: ../../compare/0.2.0...HEAD
[0.2.0]: ../../compare/0.1.1...0.2.0
[0.1.1]: ../../compare/0.1.0...0.1.1
[0.1.0]: ../../releases/tag/0.1.0
