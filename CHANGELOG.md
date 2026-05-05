# Changelog

All notable changes to usai-harness are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Auto-detect stale credentials. On a 401/403 from the endpoint in an interactive session, `USAiClient.batch()` and `USAiClient.complete()` now prompt for a fresh key (masked input), persist it to the user-level `.env`, and resume the workload from the failing task. CI and other non-TTY contexts retain the original halt-and-raise behavior. Recovery fires at most once per workload; a second consecutive auth failure re-raises the original `AuthHaltError`. Dotenv-only — Azure Key Vault rotation happens in the vault. (ADR-016)
- `usai-harness set-key [--provider NAME]` — proactive credential rotation. Prompts for a new key (masked), upserts it into the user-level `.env` under the provider's `api_key_env`, and optionally tests it against the provider's `/models` endpoint. Default `--provider` is `usai`. The key is never logged or echoed. (ADR-016)

## [0.7.0] - 2026-04-30

### Breaking
- `cost_ledger.jsonl` schema changes from one-entry-per-call to one-entry-per-(model, flush-point) pair. Each entry now reflects the *actual* model whose calls it summarizes (not the project default) and adds a `flush_reason` field with the literal values `"batch_end"` or `"client_close"`. Old ledger files remain readable as JSONL — entries from prior versions just won't have `flush_reason` and may attribute multi-model batches to the default model. Downstream tooling that depended on the old shape needs updating. (ADR-004 amendment, 2026-04-29)
- `CostTracker.__init__` signature changes: takes `pool: list[ModelConfig]` instead of `(model_name, cost_per_1k_input, cost_per_1k_output)`. `record_call` requires the model name as its first positional argument. `write_summary` is replaced by `flush_to_ledger(job_id, job_name, project, duration_seconds, flush_reason)`. `get_run_totals()` now returns a dict keyed by model name. Internal API; downstream consumers usually go through `USAiClient` and are unaffected.
- SRS FR-032 (retroactive cost computation) removed. The ledger is an estimation tool, not a billing-reconciliation artifact. Rates baked into each entry reflect the catalog values active at flush time and do not update retroactively.

### Fixed
- Multi-model pools now produce one ledger entry per model with rates derived from each model's catalog entry. Pre-0.7.0 behavior: a single entry per batch attributing all tokens to the project default's rates regardless of which models actually ran.
- `complete()`-only workflows now produce ledger entries (flushed at `client.close()`). Pre-0.7.0 behavior: silent — accumulated tokens were discarded when the client closed.

## [0.6.1] - 2026-04-29

### Added
- `usai-harness project-init` validates an existing `usai_harness.yaml` against the project-config schema before deciding to leave it alone. Schema-invalid existing files cause a non-zero exit with a per-error diagnostic plus three resolution paths, *before* the TEVV smoke test runs. Uses `jsonschema` from the `[validation]` extras when available; falls back to a keys-only check derived from the schema's `properties` otherwise. Fixes the 0.6.0 UX failure mode where a stale pre-0.6.0 YAML caused a confusing TEVV "FAIL" with no clear signal that the existing file was the problem.
- `usai-harness project-init --force` overwrites an existing `usai_harness.yaml` and bypasses the pre-flight schema check.

## [0.6.0] - 2026-04-29

The 0.6.0 release bundles three forcing-function fixes uncovered during the federal-survey-concept-mapper v2 confirmation run: principled parameter validation via a curated family catalog (ADR-014), live-catalog merge reconciliation that halts on dropped referenced models (0.5.0 inline), and the project-config schema as a first-class machine-readable artifact (ADR-015). Also lands multi-rater pool declaration at bootstrap (ADR-013 amendment).

### Breaking
- Project configs with unknown top-level fields now fail at load with `ConfigValidationError` rather than warning. The schema (ADR-015) declares `additionalProperties: false`. Migration: remove the unrecognized field, rename it to a recognized one, or run `usai-harness validate-config <path>` for a fuller diagnostic. The most common case is `project:`, `ledger_path:`, or `log_dir:` left over from the pre-0.6.0 bootstrap template; those fields were never read by the loader and are simply removed.
- A *referenced* model that is dropped by the live-catalog merge without a family-alias reconciliation match now raises `ConfigValidationError` rather than silently falling back. References are catalog-level `default_model`, project-config pool members, and project-config `default_model`. Eliminates the silent default-substitution failure mode that corrupted controlled-variation experiments. Migration: run `usai-harness discover-models` to refresh the catalog and `usai-harness list-models` to see what is currently advertised.

### Added
- Project-config JSON Schema artifact at `usai_harness/data/project_config.schema.json` (draft 2020-12). Authoritative description of the project-config field surface; `_KNOWN_PROJECT_FIELDS` is derived from it. (ADR-015)
- New CLI subcommand `usai-harness schema project-config [--format {json,yaml,markdown}]` prints the schema. The JSON form is the canonical artifact; YAML and Markdown are convenience renderings for tooling and docs. (ADR-015)
- New CLI subcommand `usai-harness validate-config <path>` validates a YAML against the schema. Pure structural validation (no catalog or credential dependencies). Requires the optional `[validation]` extras: `pip install "usai-harness[validation]"`. (ADR-015)
- New optional-dependency group `[validation]` for `jsonschema`. The three hard deps (`httpx`, `python-dotenv`, `pyyaml`) are unchanged.
- Family catalog at `usai_harness/data/families.yaml` ships with the package. Curated, citation-tier-labeled parameter specs keyed on vendor + product line + major version. Aliases preserve major version (e.g., `claude_4_5_sonnet` → `claude-sonnet-4`). (ADR-014)
- `ConfigLoader` resolves pool members through the family catalog and validates per-model parameter overrides against family rules at config-load time. Unknown aliases pass through with a warning. (ADR-014)
- New CLI subcommand `usai-harness families` prints the family catalog (table, yaml, markdown formats; optional `--family` filter). (ADR-014)
- `usai-harness project-init` supports multi-rater pool declaration via `--models MODEL1,MODEL2,...` and `--default MODEL` flags. Without flags, falls back to interactive prompt showing the catalog. Eliminates manual YAML editing for multi-rater projects. (ADR-013 amendment)

### Changed
- Bootstrap template (`project-init`) no longer emits the `project:`, `ledger_path:`, or `log_dir:` fields. The project name moves into a comment header; `cost_ledger.jsonl` and `logs/` paths remain harness-managed. The bootstrapped YAML now round-trips clean through `usai-harness validate-config`. (ADR-015)
- Live-catalog merge reconciles seed-side names against live-side names through the family-catalog alias table. When seed model `S` and live model `L` map to the same `(provider, family_key)`, `S` is treated as renamed to `L`, the seed's accounting fields (cost, context window) are carried forward, and an INFO log line records the rename. Project configs that still reference the seed name transparently pick up the live name with one INFO log per substitution. (ADR-009 / 0.5.0)
- Dropped-models warning text now includes the suggested remediation (`discover-models`, `list-models`).
- Family catalog: dated Anthropic vendor identifiers (`claude-sonnet-4-5-20241022`, `claude-opus-4-5-20250521`, `claude-3-5-haiku-20241022`) and `meta-llama/Llama-4-Maverick-17B-128E-Instruct` added to the `usai` provider alias table so they reconcile with their USAi-mapped short forms.
- Parameter validation is back, but principled. Sourced from the curated family catalog (citable, version-controlled), not from harness-internal guessing. The 0.3.0 strip-validation decision stands for catalog entries; this layer is the replacement. (ADR-012, ADR-014)

## [0.3.0] - 2026-04-29

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

[Unreleased]: ../../compare/0.7.0...HEAD
[0.7.0]: ../../compare/0.6.1...0.7.0
[0.6.1]: ../../compare/0.6.0...0.6.1
[0.6.0]: ../../compare/0.3.0...0.6.0
[0.3.0]: ../../compare/0.2.0...0.3.0
[0.2.0]: ../../compare/0.1.1...0.2.0
[0.1.1]: ../../compare/0.1.0...0.1.1
[0.1.0]: ../../releases/tag/0.1.0
