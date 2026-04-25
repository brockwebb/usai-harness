# Software Requirements Specification — usai-harness

**Version:** 1.0
**Date:** 2026-04-24
**Status:** Baseline

## 1. Purpose and Scope

The usai-harness is a Python client library for making rate-limited, model-agnostic calls to OpenAI-compatible large language model (LLM) endpoints. It is distributed as a pip-installable package intended for use by federal statistical researchers across varying security environments.

This document specifies the functional and security behavior the library shall exhibit. Quality attributes such as performance, reliability, and portability are specified separately in the NFR document.

## 2. Definitions

| Term | Definition |
|------|------------|
| Harness | The usai-harness Python package. |
| Provider | An LLM endpoint reachable over HTTP (USAi, OpenRouter, Azure OpenAI, etc.). |
| Transport | The component that executes HTTP calls to a provider. Pluggable per ADR-001. |
| Credential backend | The source of API keys (`.env`, environment variables, Azure Key Vault). Pluggable per ADR-003. |
| Model config | Entries in `configs/models.yaml` describing providers and models. |
| Project config | Per-project configuration selecting credential backend, transport, and operational parameters. |
| Job | A batch of tasks submitted together under a common job tag. |
| Task | A single LLM call request within a batch. |
| Ledger | The append-only cost record at `cost_ledger.jsonl`. |
| Call log | The per-call structured log of metadata and optional content. |

## 3. System Context

The harness is a library, not a service. It runs in-process with the calling Python program and has no daemon, no open ports, and no persistent state beyond files on the local filesystem.

Users are federal statistical researchers writing Python code that calls LLMs for tasks such as text classification, question harmonization, and extraction. The harness is called from notebooks, scripts, and pipelines. It is not called from production web services or user-facing applications.

Scope exclusions: The harness does not provide prompt engineering, response parsing, agent orchestration, or evaluation frameworks. Those concerns belong to the calling project. The harness provides rate-limited, credentialed, logged access to LLM endpoints and nothing beyond that.

## 4. Functional Requirements

### 4.1 Client Interface

**FR-001: Single-call completion.**
The harness shall provide an async `complete()` method on the client that accepts a list of messages and returns a response from the configured provider.
*Source:* Component contract in `client.py`.

**FR-002: Batch processing.**
The harness shall provide an async `batch()` method that accepts a list of task dictionaries and returns results for all tasks.
*Source:* Component contract in `client.py`.

**FR-003: Per-task parameter override.**
Each task dictionary in a batch shall accept optional per-task fields: `model`, `temperature`, `max_tokens`, `system_prompt`, `task_id`, and `metadata`. Unknown keys shall pass through to the transport.
*Source:* Component contract in `client.py`.

**FR-004: Job tagging.**
The harness shall accept a `job_name` parameter on batch calls. The job name shall be recorded in every call-log entry and ledger entry for that batch.
*Source:* Observability requirement, supports ADR-004.

**FR-005: Checkpoint and resume.**
The harness shall persist checkpoint state during batch execution such that a batch interrupted by a fatal error or by an authentication failure (FR-012) can be resumed without re-executing completed tasks.
*Source:* Reliability requirement, supports ADR-002.

### 4.2 Credential Management

**FR-006: Pluggable credential backend.**
The harness shall support multiple credential sources selectable per project: `.env` file, OS environment variables, and Azure Key Vault. The active backend shall be selected by project configuration, not by code.
*Source:* ADR-003.

**FR-007: Credential provider protocol.**
The credential layer shall expose a `CredentialProvider` protocol with a single required method `get_key(provider: str) -> str`. Additional backends shall be addable without modifying `client.py` or other modules.
*Source:* ADR-003.

**FR-008: Per-provider key isolation.**
Model configuration shall specify `api_key_env` per provider so that different providers read different keys from the same credential backend.
*Source:* ADR-003.

**FR-009: Optional Azure Key Vault backend.**
The Azure Key Vault backend shall be installed as an optional extra (`pip install -e ".[azure]"`) and shall not be required for the core library to function.
*Source:* ADR-003, ADR-005.

**FR-009a: DotEnvProvider resolution order.**
The default `DotEnvProvider` shall resolve credentials in the following order, stopping at the first match: project-local `.env` in the current working directory, user-level `.env` in the per-user configuration directory, OS environment variable named by `api_key_env` in the provider configuration. The user-level location shall be `$XDG_CONFIG_HOME/usai-harness/.env` (defaulting to `~/.config/usai-harness/.env`) on Linux and macOS, and `%APPDATA%\usai-harness\.env` on Windows.
*Source:* ADR-008.

### 4.3 Authentication Handling

**FR-010: Reactive authentication.**
The harness shall not maintain key metadata or expiry state files. Credential validity shall be determined by endpoint response.
*Source:* ADR-002.

**FR-011: Auth failure halt.**
On HTTP 401 or 403, the worker pool shall halt, checkpoint state shall be preserved, and a clear error message shall be raised instructing the user to refresh credentials.
*Source:* ADR-002.

**FR-012: Pre-flight check CLI.**
The harness shall provide a `usai-harness ping` CLI subcommand that performs a single low-cost call against the configured provider and reports success or failure.
*Source:* ADR-002.

### 4.4 Transport Layer

**FR-013: Default HTTP transport.**
The harness shall ship an `HttpxTransport` that uses `httpx` to call OpenAI-compatible endpoints and depends on no LLM framework libraries.
*Source:* ADR-001.

**FR-014: Optional LiteLLM transport.**
The harness shall provide a `LiteLLMTransport` installable as an optional extra (`pip install -e ".[litellm]"`). When installed, it shall be selectable per project via configuration.
*Source:* ADR-001.

**FR-015: Transport contract.**
Transports shall implement a common contract defined in `transport.py`. Adding a new transport shall not require changes to `client.py`, `worker_pool.py`, `rate_limiter.py`, `logger.py`, or `cost.py`.
*Source:* ADR-001.

**FR-016: OpenAI-compatible endpoint support.**
The default transport shall support any endpoint implementing the OpenAI chat-completions API schema, including USAi, OpenRouter, and Azure OpenAI.
*Source:* ADR-001.

### 4.5 Rate Limiting

**FR-017: Token bucket rate limiter.**
The harness shall limit outgoing requests using a token bucket algorithm. Refill rate and burst capacity shall be configurable per provider.
*Source:* ADR-006.

**FR-018: Default USAi rate.**
The default refill rate for the USAi provider shall be 2.8 tokens per second with burst capacity 3, providing a safety margin below the USAi 3/sec hard limit.
*Source:* ADR-006.

**FR-019: Adaptive backoff on 429.**
On HTTP 429, the harness shall reduce the current refill rate by 25 percent. On sustained successful calls, the harness shall creep the rate back up by 5 percent per window, bounded above by the configured rate and below by 0.5 tokens per second.
*Source:* ADR-006.

### 4.6 Worker Pool

**FR-020: Concurrent workers.**
The harness shall execute batch tasks using a pool of async workers. The default pool size shall be 3 workers, configurable per project.
*Source:* Component contract in `worker_pool.py`.

**FR-021: Retry with exponential backoff.**
Transient failures (network errors, HTTP 5xx, HTTP 429) shall be retried with exponential backoff. Retry count and base delay shall be configurable.
*Source:* Component contract in `worker_pool.py`.

**FR-022: Fatal error halt.**
Authentication failures (401/403) and unrecoverable transport errors shall halt the pool immediately rather than exhausting retries.
*Source:* ADR-002.

### 4.7 Configuration

**FR-023: Model configuration loading.**
The harness shall load model and provider definitions from `configs/models.yaml` using `yaml.safe_load`.
*Source:* ADR-007.

**FR-024: Project configuration loading.**
The harness shall accept optional project-level configuration overrides for credentials, transport selection, worker pool size, and rate-limit parameters.
*Source:* Component contract in `config.py`.

**FR-025: Configuration validation at init.**
Invalid configuration (missing required fields, unknown transport, unknown credential backend, malformed provider entry) shall be rejected at client initialization. The harness shall not silently fall back to defaults on invalid input.
*Source:* Fail-fast principle from CLAUDE.md.

### 4.8 Logging

**FR-026: Per-call structured logging.**
The harness shall write one structured JSONL entry per call to the call log. The log shall be flushed after each write.
*Source:* Component contract in `logger.py`.

**FR-027: Default metadata-only logging.**
The default call-log entry shall contain: timestamp, project, job, task ID, model requested, model returned, status, latency, token counts, and error category. Prompt and response content shall not be written by default.
*Source:* ADR-004, ADR-007.

**FR-028: Opt-in content logging.**
Full prompt and response logging shall be enabled via an explicit `log_content=True` flag, documented as debugging-only and potentially PII-exposing.
*Source:* ADR-004, ADR-007.

**FR-029: Model echo check.**
The harness shall record `model_requested` and `model_returned` on every call and flag mismatches in the post-run report.
*Source:* ADR-007.

### 4.9 Cost Tracking

**FR-030: Append-only cost ledger.**
The harness shall write one JSONL entry per call to `cost_ledger.jsonl`. Entries shall never be deleted, updated, or truncated by the harness.
*Source:* ADR-004.

**FR-031: Metadata-only ledger entries.**
Cost ledger entries shall contain timestamp, project, job, model, prompt tokens, completion tokens, total tokens, rate applied, and computed cost. Entries shall not contain prompt or response content. The ledger dataclass shall not have a content field.
*Source:* ADR-004, ADR-007.

**FR-032: Retroactive cost computation.**
Ledger entries shall record the rate applied at the time of the call. Changes to rates in `models.yaml` shall not invalidate historical ledger entries.
*Source:* ADR-004.

### 4.10 Reporting

**FR-033: Post-run summary.**
At the end of each batch, the harness shall emit a summary report covering call count, success rate, total tokens, total cost, observed rate-limit behavior, and any model-echo mismatches.
*Source:* Component contract in `report.py`.

**FR-034: Cost report CLI.**
The harness shall provide a `usai-harness cost-report` CLI subcommand that aggregates ledger entries by project, job, and model over a user-specified time range.
*Source:* Component contract in `report.py`.

**FR-035: Audit CLI.**
The harness shall provide a `usai-harness audit` CLI subcommand that checks gitignore coverage for sensitive files, scans for accidentally tracked secrets, and runs `pip-audit` against the current environment.
*Source:* ADR-007.

### 4.11 Setup and Model Discovery

**FR-036: Interactive first-run setup.**
The harness shall provide a `usai-harness init` CLI subcommand that prompts for provider name, base URL, and API key; writes credentials to the user-level location defined in FR-009a; queries the provider's model list endpoint; writes the resulting model catalog to the user-level configuration; and executes a test completion to verify the setup end-to-end. The command shall be idempotent against re-run.
*Source:* ADR-009.

**FR-037: Additional provider registration.**
The harness shall provide a `usai-harness add-provider NAME` CLI subcommand (where `NAME` is the provider identifier, for example `openrouter`) that prompts for a base URL and key for the named provider, verifies reachability, retrieves the model catalog, and updates the user-level configuration. The command shall not affect other providers already configured.
*Source:* ADR-009.

**FR-038: Model catalog refresh.**
The harness shall provide a `usai-harness discover-models [provider]` CLI subcommand that queries the model list endpoint for the named provider (or all providers if the argument is omitted) and rewrites the user-level model catalog. The command shall not modify credentials or the repository-level `configs/models.yaml`.
*Source:* ADR-009.

**FR-039: End-to-end verification.**
The harness shall provide a `usai-harness verify` CLI subcommand that for each configured provider resolves the credential, reaches the base URL, retrieves the model catalog, and executes a test completion. The command shall report per-provider pass or fail status. `verify` is the complete health check; `ping` (FR-012) is a minimal single-call check against the default provider.
*Source:* ADR-009.

**FR-040: Endpoint as source of truth for model identity.**
The live model catalog retrieved from the provider endpoint shall be the authoritative list of valid model identifiers. Entries in the repository-level `configs/models.yaml` shall supply presentation overrides (display name, temperature range, cost rates) but shall not assert which models exist.
*Source:* ADR-009.

**FR-041: Non-echoing key capture.**
Interactive subcommands that prompt for API keys shall use `getpass.getpass()` or an equivalent non-echoing input method. Keys shall not be echoed to the terminal and shall not be captured by shell history mechanisms during interactive prompting.
*Source:* ADR-009.

## 5. Security Requirements

**SEC-001: Secret redaction.**
All logs, error messages, and stack traces emitted by the harness shall be scrubbed of `Bearer` tokens and any string matching the configured key pattern before being written to disk or emitted to stderr.
*Source:* ADR-007.

**SEC-002: Safe YAML loading.**
The harness shall use `yaml.safe_load` exclusively. The codebase shall contain no calls to `yaml.load` or equivalent unsafe loaders.
*Source:* ADR-007.

**SEC-003: TLS verification.**
The default transport shall use TLS verification. If a user disables verification, the harness shall emit a warning to stderr on every call.
*Source:* ADR-007.

**SEC-004: No secrets in config files.**
The harness shall not require secrets to be stored in `configs/models.yaml` or any committed configuration file. All credentials shall be resolved through a credential backend (FR-006).
*Source:* ADR-003.

**SEC-005: Gitignore coverage.**
The repository shall gitignore `.env`, `cost_ledger.jsonl`, `logs/`, and any other files that may contain secrets or call content. The `usai-harness audit` command shall verify coverage.
*Source:* ADR-007.

**SEC-006: Hash-pinned dependencies.**
The repository shall provide a `requirements.lock` file with package hashes suitable for `pip install --require-hashes`.
*Source:* ADR-005, ADR-007.

## 6. Interface Requirements

**IR-001: Public API.**
The public API shall consist of the `USAiClient` class exported from `usai_harness`. The public methods shall be `complete()`, `batch()`, and async context management (`__aenter__`/`__aexit__`).

**IR-002: CLI entry point.**
The package shall register a `usai-harness` console entry point. Subcommands shall include `init`, `add-provider`, `discover-models`, `verify`, `ping`, `cost-report`, and `audit`.

**IR-003: Model configuration schema.**
`configs/models.yaml` shall declare providers and models. Each provider entry shall specify `base_url`, a credential reference, rate-limit parameters, and a list of supported model identifiers. The credential reference is `api_key_env` (an environment variable name) for the `dotenv` and `env_var` backends, or `api_key_secret` (a Key Vault secret name) for the `azure_keyvault` backend. A provider entry may specify both fields when it supports multiple backends. For the Azure backend, `api_key_env` is accepted as a deprecated fallback in 0.1.x and shall be removed in 0.2.0. Each model entry shall specify token-cost rates.

**IR-004: Project configuration schema.**
Project configuration shall accept a `credentials` block selecting the backend, a `transport` field selecting httpx or litellm, and optional overrides for worker pool size and rate-limit parameters.

## 7. Constraints and Assumptions

**C-001:** Python 3.12 or higher is required. Development target is 3.14.
**C-002:** Hard dependencies are limited to `httpx`, `python-dotenv`, and `pyyaml`. Other functionality is delivered via optional extras.
**C-003:** The harness is a library, not a service. It does not provide a daemon, an HTTP server, or persistent background processes.
**C-004:** The harness assumes the calling environment has outbound HTTPS access to the configured provider endpoints.
**C-005:** The harness does not manage model provenance, content moderation, or output validation beyond model-echo checking (FR-029).

## 8. Traceability

Requirements shall be traced to implementing modules, tests, and verification methods in the Requirements Traceability Matrix (RTM). Each FR, SEC, and IR in this document appears in the RTM with links to source code, test cases, and applicable ADRs.
