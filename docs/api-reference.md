# API Reference — usai-harness

**Version:** 1.0
**Date:** 2026-04-24

This document specifies the public API, configuration schemas, CLI interface, and extension protocols. For usage walkthroughs see the README and Operations Guide.

## 1. Public Python API

### 1.1 `USAiClient`

The single public class. Manages lifecycle for credentials, transport, rate limiting, logging, and cost tracking.

```python
from usai_harness import USAiClient

async with USAiClient(
    project: str,
    config_path: str | Path | None = None,
) as client:
    ...
```

**Parameters:**

- `project` (str, required): Identifier for this project. Appears in logs, ledger entries, and reports. Used to group cost and usage aggregations.
- `config_path` (str or Path, optional): Path to a project-specific configuration file. If omitted, the harness looks for `usai-harness.yaml` in the current working directory, then falls back to defaults.

**Context management:** The client uses async context management. Entering initializes components and validates configuration. Exiting flushes logs, closes HTTP connections, and finalizes the cost ledger.

### 1.2 `complete()`

Single-call completion.

```python
async def complete(
    self,
    messages: list[dict],
    *,
    model: str | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
    **extra_params,
) -> CompletionResponse:
    ...
```

**Parameters:**

- `messages`: List of message dictionaries in OpenAI chat format. Required.
- `model`: Model identifier. If omitted, the default model from the active provider configuration is used.
- `provider`: Provider identifier. If omitted, the default provider is used.
- `temperature`, `max_tokens`, `system_prompt`: Standard generation parameters. If omitted, provider or model defaults apply.
- `**extra_params`: Any additional keyword arguments are passed through to the transport as provider-specific parameters.

**Returns:** A `CompletionResponse` with fields for `content`, `model_requested`, `model_returned`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`, and `latency_ms`.

**Raises:**

- `AuthenticationError` on HTTP 401 or 403.
- `ConfigurationError` on invalid parameters.
- `TransportError` for network or provider errors not covered by retry.

### 1.3 `batch()`

Batch processing with rate limiting, retries, and checkpoint support.

```python
async def batch(
    self,
    tasks: list[dict],
    *,
    job_name: str,
    log_content: bool = False,
    checkpoint_path: str | Path | None = None,
) -> list[CompletionResponse]:
    ...
```

**Parameters:**

- `tasks`: List of task dictionaries. Each must contain a `messages` field. Optional per-task fields: `model`, `provider`, `temperature`, `max_tokens`, `system_prompt`, `task_id`, `metadata`. Any other fields pass through to the transport.
- `job_name`: Identifier for this batch. Appears in logs and ledger entries. Used for checkpoint and resume.
- `log_content`: If `True`, prompts and responses are written to the call log for this batch only. Default is `False`. See Section 5 for why you should leave this off unless debugging.
- `checkpoint_path`: Where to write checkpoint state during the batch. Default is `checkpoints/{job_name}.json` in the working directory.

**Returns:** A list of `CompletionResponse` objects, one per task, in the same order as the input.

**Raises:**

- `AuthenticationError` if the credential fails. Checkpoint is preserved; resume via `batch()` with the same `job_name` picks up where it left off.
- `ConfigurationError` at start if the task list is malformed.

### 1.4 Resume after auth failure

If a batch halts on authentication failure, refresh the credential (see Operations Guide Section 2), then call `batch()` again with the same `job_name`:

```python
# First attempt: halts on auth failure after 47 tasks
try:
    results = await client.batch(tasks, job_name="my-batch")
except AuthenticationError:
    # User refreshes credential
    ...

# After refresh, resume picks up at task 48
results = await client.batch(tasks, job_name="my-batch")
```

The harness detects the existing checkpoint and skips completed tasks. Results returned by the resumed call include all tasks, both those completed before the halt and those completed after.

### 1.5 `CompletionResponse`

```python
@dataclass
class CompletionResponse:
    content: str
    model_requested: str
    model_returned: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    latency_ms: int
    task_id: str | None = None
    metadata: dict | None = None
    error: str | None = None
```

When `error` is non-None, `content` may be empty and other fields may be zero. The task is still included in batch results so callers can see which tasks failed.

## 2. Configuration

### 2.1 Model configuration (`configs/models.yaml`)

The repository ships a default model configuration. Users also maintain a user-level version at the path defined in FR-009a. The user-level version is authoritative for which models are available (built by `init` and `discover-models`). The repository-level version provides presentation overrides and serves as a seed for unfamiliar providers.

```yaml
providers:
  usai:
    base_url: https://usai.example.gov
    api_key_env: USAI_API_KEY
    rate:
      refill_per_sec: 2.8
      burst: 3
    default_model: claude-sonnet-4-5-20241022

  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    rate:
      refill_per_sec: 10
      burst: 20

models:
  - id: claude-sonnet-4-5-20241022
    name: "Claude Sonnet 4.5"
    provider: usai
    temp_range: [0.0, 1.0]
    temp_default: 0.5
    input_rate_per_1k: 0.003
    output_rate_per_1k: 0.015
```

**Top-level fields:**

- `error_body_snippet_max_chars` (optional, default 200): Maximum character length of the error body snippet captured from non-2xx responses and written to the call log under `error_body`. Valid range 1 through 2000 inclusive. Configurations specifying values outside this range are rejected at load with `ConfigValidationError`. See section 5.1 for the snippet semantics.

**Provider fields:**

- `base_url` (required): Root URL of the provider. The harness appends `/chat/completions` and `/models` to the configured base URL as needed; the path prefix (such as `/api/v1` or `/v1beta/openai`) belongs in `base_url`.
- `api_key_env` (one of two credential references): Name of the environment variable or `.env` key that holds the API key for this provider. Required for `dotenv` and `env_var` credential backends.
- `api_key_secret` (one of two credential references): Name of the secret in the configured Key Vault. Required for the `azure_keyvault` credential backend. For Azure backends, `api_key_env` is accepted as a deprecated fallback in 0.1.x (with `DeprecationWarning`); removal target 0.2.0.
- `rate` (optional): Rate-limit parameters. Defaults to 2.8/sec refill with burst 3.
- `default_model` (optional): Model to use when a call does not specify one.

**Model fields:**

- `id` (required): Exact model identifier as returned by the provider's model list endpoint.
- `provider` (required): Provider identifier this model belongs to.
- `name` (optional): Display name for reports.
- `temp_range`, `temp_default` (optional): Temperature bounds and default.
- `input_rate_per_1k`, `output_rate_per_1k` (optional): Cost per thousand tokens for input and output. Defaults to zero (free credit periods).

### 2.2 Project configuration (`usai-harness.yaml`)

Project-level overrides go in a `usai-harness.yaml` file in the project root. All fields are optional.

```yaml
credentials:
  backend: dotenv              # dotenv | envvar | azure_keyvault
  vault_url: null              # required when backend is azure_keyvault
  secret_name: null            # required when backend is azure_keyvault

transport: httpx               # httpx | litellm

default_provider: usai
default_model: claude-sonnet-4-5-20241022

workers: 3                     # parallel workers, default 3

rate_overrides:
  usai:
    refill_per_sec: 2.5        # tighter than global default for this project
```

Invalid fields cause the client to fail at initialization with a specific error message.

## 3. CLI Reference

All subcommands accept `--help` for usage details.

### 3.1 `usai-harness init`

First-run setup. Prompts for provider name, base URL, and API key. Writes to user-level config. Fetches the model catalog. Runs a test call. Reports success or specific failure.

```
usai-harness init [--provider NAME]
```

- `--provider NAME`: Set the provider name without prompting. Default is `usai`.

Idempotent. Safe to re-run.

### 3.2 `usai-harness add-provider`

Register an additional provider.

```
usai-harness add-provider NAME [--base-url URL] [--api-key-env VAR]
```

- `NAME` (required): Provider identifier (for example `openrouter`).
- `--base-url`: Skip the base URL prompt.
- `--api-key-env`: Environment variable name to store the key under. Defaults to `{NAME_UPPER}_API_KEY`.

### 3.3 `usai-harness discover-models`

Refresh the model catalog from one or all providers.

```
usai-harness discover-models [PROVIDER]
```

- `PROVIDER` (optional): Refresh only the specified provider. If omitted, all configured providers are refreshed.

Does not touch credentials. Does not modify repository-level `configs/models.yaml`. Updates user-level model catalog.

### 3.4 `usai-harness verify`

End-to-end health check.

```
usai-harness verify [--provider NAME]
```

- `--provider NAME`: Check only the specified provider. If omitted, all are checked.

Reports per-provider: credential resolves, endpoint reachable, model catalog retrieved, test call succeeded. Exit code 0 only when everything passes.

### 3.5 `usai-harness ping`

Minimal single-call check. Faster than `verify`. Useful for scripted pre-flight checks.

```
usai-harness ping [--provider NAME]
```

- `--provider NAME`: Check only the specified provider. Defaults to the default provider.

### 3.6 `usai-harness cost-report`

Aggregate cost ledger entries.

```
usai-harness cost-report [--project NAME] [--job NAME] [--since DATE] [--until DATE] [--by FIELD]
```

- `--project NAME`: Filter to a specific project.
- `--job NAME`: Filter to a specific job.
- `--since DATE`: Include only entries at or after this date (YYYY-MM-DD).
- `--until DATE`: Include only entries at or before this date (YYYY-MM-DD).
- `--by FIELD`: Group output by `project`, `job`, `model`, or `day`. Default is `project`.

Outputs a summary table to stdout.

### 3.7 `usai-harness audit`

Security hygiene check.

```
usai-harness audit [--fix-gitignore]
```

- `--fix-gitignore`: If gitignore coverage is missing, append the required lines automatically. Default is to report only.

Reports gitignore coverage, tracked-secret scan results, and `pip-audit` output. Exit code 0 only when all three pass.

## 4. Extension Protocols

For advanced users adding a new transport or credential backend.

### 4.1 `Transport` protocol

```python
from typing import Protocol

class Transport(Protocol):
    async def request(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        api_key: str,
        **params,
    ) -> TransportResponse:
        ...
```

**Implementations ship with the library:**

- `HttpxTransport` in `usai_harness.transport`
- `LiteLLMTransport` in `usai_harness.transport.litellm` (requires `.[litellm]`)

**To add a new transport:**

1. Implement the protocol.
2. Register the class in your project configuration under `transport`.
3. The client will instantiate and use it at runtime.

### 4.2 `CredentialProvider` protocol

```python
class CredentialProvider(Protocol):
    def get_key(self, provider: str) -> str:
        ...
```

**Implementations ship with the library:**

- `DotEnvProvider` (default)
- `EnvVarProvider`
- `AzureKeyVaultProvider` (requires `.[azure]`)

**Credential reference field**

The `providers:` block in `configs/models.yaml` carries one credential reference per entry. The field is named per backend.

For `DotEnvProvider` and `EnvVarProvider`, set `api_key_env` to the environment variable name from which the key is read. The DotEnv provider checks the project-local `.env`, then the user-level `.env`, then the OS environment in that order; the env-var provider checks only the OS environment.

For `AzureKeyVaultProvider`, set `api_key_secret` to the secret name in the configured Key Vault. The provider's `vault_url` selects which vault.

A provider entry may set both fields. The active credentials backend determines which is read. For the Azure backend, `api_key_env` is accepted as a deprecated fallback in 0.1.x and emits a `DeprecationWarning` at config load. Removal target is 0.2.0. Migration: rename `api_key_env` to `api_key_secret` in `providers:` entries that point at Azure-backed credentials.

**To add a new backend:**

1. Implement the protocol.
2. Register the backend name in your project configuration under `credentials.backend`.
3. The client will resolve credentials through your provider at runtime.

Providers do not implement freshness or expiry logic. The harness uses reactive authentication (ADR-002). If the credential is invalid, the endpoint will return 401 and the harness will handle the failure cleanly.

## 5. On-Disk Artifacts

### 5.1 Call log format (`logs/calls.jsonl`)

One JSON object per line. Default entry:

```json
{
  "timestamp": "2026-04-24T14:23:11.412Z",
  "project": "my-project",
  "job": "my-batch",
  "task_id": "q_0042",
  "model_requested": "claude-sonnet-4-5-20241022",
  "model_returned": "claude-sonnet-4-5-20241022",
  "provider": "usai",
  "status": "success",
  "latency_ms": 847,
  "prompt_tokens": 124,
  "completion_tokens": 512,
  "total_tokens": 636,
  "error_category": null
}
```

When `log_content=True` is set on a batch, two additional fields appear: `prompt` (list of message dicts) and `response` (string). These fields are omitted entirely when `log_content` is false, not just empty.

Failed call entry:

```json
{
  "timestamp": "2026-04-24T14:23:11.412Z",
  "project": "my-project",
  "job": "my-batch",
  "task_id": "q_0042",
  "model_requested": "gemini-2.5-flash",
  "model_returned": null,
  "provider": "gemini",
  "status": "failed",
  "status_code": 400,
  "latency_ms": 312,
  "error": "HTTP 400: non-retryable status",
  "error_body": "{\"error\":{\"code\":400,\"message\":\"API key not valid. Please pass a valid API key.\",\"status\":\"INVALID_ARGUMENT\"}}"
}
```

The `error_body` field appears on failed-call entries and contains a redacted snippet of the response body, truncated to `error_body_snippet_max_chars` (default 200) characters. The snippet passes through `redact_secrets()` before being written; Bearer headers and provider-shaped key strings are scrubbed. Binary content types (anything not `application/json` or `text/*`) are not captured. The field is omitted entirely on successful calls and on failed calls where body capture failed (read error, encoding error, or empty body).

The call log is always flushed after each write. Readers tailing the file see entries in near real time.

### 5.2 Cost ledger format (`cost_ledger.jsonl`)

One JSON object per line. Append-only. The ledger dataclass structurally cannot contain content.

```json
{
  "timestamp": "2026-04-24T14:23:11.412Z",
  "project": "my-project",
  "job": "my-batch",
  "task_id": "q_0042",
  "model": "claude-sonnet-4-5-20241022",
  "provider": "usai",
  "prompt_tokens": 124,
  "completion_tokens": 512,
  "total_tokens": 636,
  "input_rate_per_1k": 0.003,
  "output_rate_per_1k": 0.015,
  "cost": 0.008052
}
```

The ledger is durable. Entries are flushed after each write. An interrupted batch may be missing its last entry if the process died before flush; successful calls that completed before interruption are safe.

### 5.3 Post-run report format

The post-run report returned by `batch()` is a `BatchReport` dataclass:

```python
@dataclass
class BatchReport:
    project: str
    job_name: str
    started_at: datetime
    completed_at: datetime
    total_calls: int
    successful: int
    failed: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost: float
    rate_limit_events: int
    model_echo_mismatches: list[dict]
    errors_by_category: dict[str, int]
```

Serialized to JSON and written alongside the call log at `logs/reports/{job_name}_{timestamp}.json`.

## 6. Error Types

All raised exceptions inherit from `UsaiHarnessError`.

- `ConfigurationError`: Invalid configuration or parameters. Caught at init.
- `AuthenticationError`: HTTP 401 or 403 from the provider. Raised by `complete()` or `batch()`. Preserves checkpoint. Provider endpoints differ in which HTTP status they return for an invalid API key. USAi returns 401 or 403, both of which raise `AuthenticationError` and halt the worker pool. Gemini's OpenAI-compat endpoint returns 400 with a structured error body, which the harness treats as a per-call non-retryable failure rather than an auth halt. See `docs/ops-guide.md` section 7.1 for the operational implications and the recommended pre-flight mitigation.
- `TransportError`: Network failure, DNS issue, TLS error, or provider error not covered by retry.
- `RateLimitError`: Sustained rate-limit failure after adaptive backoff exhausts. Rare; usually indicates a misconfiguration or provider outage.
- `ModelNotFoundError`: Requested model is not in the provider's current catalog. Run `discover-models` to refresh.
- `CheckpointError`: Checkpoint file is corrupt or inconsistent with the task list. Delete the checkpoint and restart, or investigate.

Every exception carries a human-readable message and, where applicable, a `.context` dict with the provider, model, task_id, and relevant HTTP status for diagnostic use.

## 7. Deprecation Policy

Public API additions follow semantic versioning. Deprecated functions emit `DeprecationWarning` for at least one minor version before removal. Configuration schema changes do the same: an old-format config loads with warnings for a full minor-version cycle before being rejected.

Private modules and internal helpers (anything prefixed with `_` or documented as internal) can change without notice. Do not import them.
