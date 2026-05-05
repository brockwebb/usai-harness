# API Reference — usai-harness

**Version:** 1.0
**Date:** 2026-04-24

This document specifies the public API, configuration schemas, CLI interface, and extension protocols. For usage walkthroughs see the README and Operations Guide.

## 1. Public Python API

See also: `docs/examples/` contains three runnable scripts that exercise the surface described in this section.

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
- `model`: Model identifier. Must be a member of the project config's pool. If omitted, the project's `default_model` is used. Passing a model that is not in the pool raises `ValueError`.
- `provider`: Provider identifier. If omitted, the default provider is used.
- `temperature`, `max_tokens`, `system_prompt`: Standard generation parameters. When provided, they are validated against the chosen model's catalog ranges (not the default model's). When omitted, the project-default values apply, falling back to the catalog defaults for the chosen model.
- `**extra_params`: Any additional keyword arguments are passed through to the transport as provider-specific parameters.

**Returns:** A `CompletionResponse` with fields for `content`, `model_requested`, `model_returned`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`, and `latency_ms`.

**Raises:**

- `ValueError` when `model` is not in the project's pool, or when `temperature`/`max_tokens` is out of range for the chosen model.
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

- `tasks`: List of task dictionaries. Each must contain a `messages` field. Optional per-task fields: `model` (must be a pool member), `provider`, `temperature`, `max_tokens`, `system_prompt`, `task_id`, `metadata`. Any other fields pass through to the transport. Per-task `model` and `temperature` are validated at task-build time against the chosen model's catalog entry; mismatches raise before any HTTP traffic, so a typo or out-of-range value fails fast.
- `job_name`: Identifier for this batch. Appears in logs and ledger entries. Used for checkpoint and resume.
- `log_content`: If `True`, prompts and responses are written to the call log for this batch only. Default is `False`. See Section 5 for why you should leave this off unless debugging.
- `checkpoint_path`: Where to write checkpoint state during the batch. Default is `checkpoints/{job_name}.json` in the working directory.

**Returns:** A list of `CompletionResponse` objects, one per task, in the same order as the input.

**Raises:**

- `ValueError` when a task selects a model that is not in the pool, or when a task's `temperature`/`max_tokens` is out of range for the chosen model.
- `AuthenticationError` if the credential fails. Checkpoint is preserved; resume via `batch()` with the same `job_name` picks up where it left off.
- `ConfigurationError` at start if the task list is malformed.

**Example: mixed-model batch.** Each task can target a different pool member; the worker pool dispatches them through the same client without per-model setup:

```python
async with USAiClient(project="rater-ensemble") as client:
    tasks = [
        {"messages": [{"role": "user", "content": q}],
         "model": "claude-sonnet-4-5-20241022", "task_id": f"sonnet_{i:03d}"}
        for i, q in enumerate(questions)
    ] + [
        {"messages": [{"role": "user", "content": q}],
         "model": "claude-opus-4-5-20250521", "task_id": f"opus_{i:03d}"}
        for i, q in enumerate(questions)
    ]
    results = await client.batch(tasks, job_name="multi-rater")
```

Both models must be members of the pool declared in `usai_harness.yaml`; both must share the same provider (cross-provider pools are rejected).

### 1.4 Resume after auth failure

When stdin is interactive (i.e. running from a terminal), `USAiClient.batch()` and `USAiClient.complete()` recover transparently from a stale credential per ADR-016. On a 401/403, the harness prompts for a fresh key (masked input), persists it to the user-level `.env`, and resumes the workload — `batch()` re-runs the failing task and any deferred tasks while keeping successful results from before the halt; `complete()` retries once with the new key. Recovery fires at most once per workload; a second consecutive auth failure re-raises the original `AuthHaltError`.

In non-TTY contexts (CI, piped stdin), recovery is skipped and the original halt-and-raise behavior applies. The same is true for `AzureKeyVaultProvider`-backed projects, where rotation happens in the vault rather than in the harness.

For proactive rotation (the user knows a fresh key is coming), `usai-harness set-key [--provider NAME]` updates the credential without triggering an auth halt. See section 3.3a.

If you do need to handle the halt manually — for example in a non-TTY context where recovery is skipped — refresh the credential and call `batch()` again with the same `job_name`:

```python
# First attempt halts on auth failure after 47 tasks (non-TTY context).
try:
    results = await client.batch(tasks, job_name="my-batch")
except AuthHaltError:
    # User refreshes credential out-of-band, e.g. via `usai-harness set-key`.
    ...

# After refresh, the resumed call picks up where the halt left off.
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

- `base_url` (required): Root URL of the provider, including any API path prefix (such as `/api/v1` or `/v1beta/openai`). The transport appends `/chat/completions` and `/models` to whatever value is stored. The `usai-harness init` flow auto-detects the prefix during setup, so users typically paste the bare hostname and the resolved URL is what gets written here.
- `api_key_env` (one of two credential references): Name of the environment variable or `.env` key that holds the API key for this provider. Required for `dotenv` and `env_var` credential backends.
- `api_key_secret` (one of two credential references): Name of the secret in the configured Key Vault. Required for the `azure_keyvault` credential backend. An Azure provider entry that omits `api_key_secret` raises `ConfigValidationError` at load; `api_key_env` is not accepted as a synonym.
- `rate` (optional): Rate-limit parameters. Defaults to 2.8/sec refill with burst 3.
- `default_model` (optional): Model to use when a call does not specify one.

**Model fields:**

- `id` (required): Exact model identifier as returned by the provider's model list endpoint.
- `provider` (required): Provider identifier this model belongs to.
- `name` (optional): Display name for reports.
- `temp_range`, `temp_default` (optional): Temperature bounds and default.
- `input_rate_per_1k`, `output_rate_per_1k` (optional): Cost per thousand tokens for input and output. Defaults to zero (free credit periods).

### 2.2 Project configuration (`usai_harness.yaml`)

Project-level configuration lives in a single file named `usai_harness.yaml` at the project root (ADR-011). The harness discovers this file automatically when `USAiClient` is instantiated from the project root; pass `config_path=` explicitly when your script runs from elsewhere. The `usai-harness project-init` command writes this file with sensible defaults; the example below shows the schema after that file has been edited for a multi-model project.

```yaml
project: rater-ensemble
provider: usai                 # must match every pool member's catalog provider

models:
  - name: claude-sonnet-4-5-20241022
    # Optional per-model overrides; uncomment to set.
    # temperature: 0
    # max_tokens: 4096
  - name: claude-opus-4-5-20250521
  - name: gemini-2.5-flash

default_model: claude-sonnet-4-5-20241022

# Concurrency
workers: 3                     # parallel workers, default 3
batch_size: 50                 # default batch size for cost reporting

# Project-default request parameters (validated against default_model's catalog ranges)
temperature: 0.0
max_tokens: null               # falls back to default_model.max_output_tokens

# Output paths (relative to project root or absolute)
ledger_path: output/cost_ledger.jsonl
log_dir: output/logs

# Optional credential backend override (defaults to dotenv)
credentials:
  backend: dotenv              # dotenv | env_var | azure_keyvault
  # vault_url: ...             # required when backend is azure_keyvault
```

**Key fields**

- `models` (required): A list of pool members. Each entry is a string model name or a mapping with a `name` key plus optional per-model `temperature` / `max_tokens` overrides. Every member must exist in the merged catalog, and per-member overrides are validated against the *target model's* catalog ranges, not the default model's.
- `default_model` (required when `models` has more than one member): A pool member that becomes the default for tasks that do not specify `model`. With a single-member pool, `default_model` may be omitted and that member is the default.
- `provider` (required when pool members come from multiple providers in the catalog): The endpoint provider for every pool member. Cross-provider pools are rejected; instantiate one client per provider in projects that genuinely need that.
- `workers`, `batch_size`, `temperature`, `max_tokens`, `system_prompt`: Project-default request parameters. Per-task overrides are validated against the *task's chosen model* at task-build time.
- `credentials.backend`: Selects which `CredentialProvider` resolves the API key. See section 4.2.

**Backward compatibility.** A legacy single-`model:` field is translated automatically to a one-element pool with that model as default; no warning is emitted. Configs that declare both `model:` and `models:` are rejected at load.

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

### 3.3a `usai-harness set-key`

Rotate the credential for a provider (ADR-016). Prompts for a fresh key with masked input, persists it to the user-level `.env` under the provider's `api_key_env` variable, and optionally tests the new key against the provider's `/models` endpoint.

```
usai-harness set-key [--provider NAME]
```

- `--provider NAME`: Provider whose credential to rotate. Default: `usai`.

Exit 0: key saved (a failed connectivity test prints a stderr warning but does not block the save). Exit 1: unknown provider, empty key entered, Azure-style entry without `api_key_env`, or KeyboardInterrupt at the prompt. The key is never logged or echoed; only `"New key saved for <provider>."` plus the optional connectivity test result appears on stdout.

For dotenv-backed providers only. Azure Key Vault rotation happens in the vault, not in the harness; `set-key` against a Key Vault entry exits 1 with a message pointing at the vault.

### 3.4 `usai-harness list-models`

Print the merged catalog (repository seed plus user-level catalog) so you can see exactly which model names you can declare in a `usai_harness.yaml` pool.

```
usai-harness list-models [--provider NAME] [--format {table,yaml,names}]
```

- `--provider NAME`: Filter to one provider.
- `--format`: Output format. `table` is the default and is intended for human reading. `yaml` dumps a `providers: {NAME: {models: [...]}}` structure suitable for piping or copying. `names` emits one model name per line for use with `grep`, `xargs`, and similar.

Read-only. Returns 0 if at least one entry remains after filtering, 1 if the catalog is empty (run `init` or `discover-models`) or the provider filter matches nothing.

### 3.5 `usai-harness verify`

End-to-end health check.

```
usai-harness verify [--provider NAME]
```

- `--provider NAME`: Check only the specified provider. If omitted, all are checked.

Reports per-provider: credential resolves, endpoint reachable, model catalog retrieved, test call succeeded. Exit code 0 only when everything passes.

### 3.6 `usai-harness ping`

Minimal single-call check. Faster than `verify`. Useful for scripted pre-flight checks.

```
usai-harness ping [--provider NAME]
```

- `--provider NAME`: Check only the specified provider. Defaults to the default provider.

### 3.7 `usai-harness cost-report`

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

### 3.8 `usai-harness audit`

Security hygiene check.

```
usai-harness audit [--fix-gitignore]
```

- `--fix-gitignore`: If gitignore coverage is missing, append the required lines automatically. Default is to report only.

Reports gitignore coverage, tracked-secret scan results, and `pip-audit` output. Exit code 0 only when all three pass.

### 3.9 `usai-harness project-init`

Bootstrap the current directory as a project. Creates `usai_harness.yaml`, `output/`, `tevv/`, `scripts/example_batch.py`, and a TEVV smoke-test report.

```
usai-harness project-init [--models MODEL1,MODEL2,...] [--default MODEL] [--force]
```

- `--models`: Pool members as a comma-separated list of catalog names. Each name must exist in the merged catalog (run `usai-harness list-models` first to see what is available).
- `--default`: Default model for the pool. Must be one of `--models`. Required to skip the prompt when the pool has more than one member.
- `--force`: Overwrite an existing `usai_harness.yaml`. Without `--force`, an existing file is validated against the schema; a schema-invalid file causes a non-zero exit *before* TEVV runs (so the user sees a structural diagnostic rather than a workload-time failure). With `--force`, the file is replaced with a freshly-rendered template.

Without flags, `project-init` shows the catalog as a numbered list and prompts for the pool selection (and the default model if the pool has more than one member). When stdin is not a TTY, it falls back to a single-rater pool with the user-level default model. CI and scripted bootstraps should always pass `--models` and `--default` to avoid hanging on a prompt.

Pre-flight schema check on an existing config (added 0.6.1): when `usai_harness.yaml` already exists and `--force` is absent, the file is validated against the project-config schema before bootstrap proceeds. The check uses `jsonschema` from the `[validation]` extras when installed; otherwise it falls back to a keys-only check derived from the schema's `properties`. Schema-invalid files cause a non-zero exit with a per-error diagnostic plus three resolution paths: delete the file and re-run, hand-edit and re-run, or pass `--force` to overwrite.

Cross-provider pools are rejected at bootstrap (ADR-012). Pick from a single provider, or run `project-init` twice with separate pools.

Per-model parameter overrides (such as `temperature: 0.1` on a specific Gemini entry) are not flag-driven; edit the generated `usai_harness.yaml` for those.

### 3.10 `usai-harness schema project-config`

Print the project-config JSON Schema (ADR-015). This artifact is the single source of truth for what fields are valid in `usai_harness.yaml`.

```
usai-harness schema project-config [--format {json,yaml,markdown}]
```

- `--format json` (default): the canonical artifact, suitable for tooling.
- `--format yaml`: a YAML rendering of the same schema.
- `--format markdown`: a human-readable table of fields, types, and descriptions for embedding in docs.

The schema is shipped at `usai_harness/data/project_config.schema.json` inside the package. Downstream consumers should reference this command rather than copying field-level rules into their own documentation.

### 3.11 `usai-harness validate-config`

Validate a YAML file against the project-config schema (ADR-015).

```
usai-harness validate-config PATH
```

- `PATH`: path to the YAML file to check.

This is pure schema validation. It catches structural problems (unknown fields, wrong types, missing required fields). It does NOT consult the live catalog, resolve model names, or touch credentials; catalog membership and family-catalog parameter ranges are enforced separately by `load_project_config()` at workload time.

Exits 0 with `OK: <path> validates against project_config_v1.` on success. Exits 1 with one error per line on failure. Requires the optional `[validation]` extras group: `pip install "usai-harness[validation]"`.

## 4. Project Config Schema

The authoritative artifact is `usai_harness/data/project_config.schema.json`. JSON Schema draft 2020-12, `$id` `https://schemas.anthropic.invalid/usai-harness/project-config-v1.json`.

To get a snapshot in a format other than JSON, use `usai-harness schema project-config --format markdown`. The schema is also embedded at the path above for IDE tooling: add `# yaml-language-server: $schema=<schema $id>` at the top of your `usai_harness.yaml` to enable autocomplete in VS Code's YAML extension once the schema URL is publicly resolvable.

The schema's `additionalProperties: false` is enforced at config load: a project config with unknown top-level fields fails with `ConfigValidationError` rather than warning. Use `usai-harness validate-config <path>` to find offending fields before running a workload.

What the schema does NOT encode:

- Catalog membership. Model names are validated against the merged runtime catalog at load time; the schema only checks that names are non-empty strings.
- Family-catalog parameter ranges (e.g., Gemini 2.5 accepts `temperature` in `[0.0, 2.0]`). Those live in the family catalog (ADR-014) and apply at load time, not at schema-validation time.
- Credentials backend kwargs. The schema enumerates the recognized backends; backend-specific kwargs flow through under `credentials` as additional properties.

## 5. Extension Protocols

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

A provider entry may set both fields. The active credentials backend determines which is read. The Azure backend strictly requires `api_key_secret`; an Azure provider that only declares `api_key_env` raises `ConfigValidationError`. The previous deprecation-window fallback was removed.

**To add a new backend:**

1. Implement the protocol.
2. Register the backend name in your project configuration under `credentials.backend`.
3. The client will resolve credentials through your provider at runtime.

Providers do not implement freshness or expiry logic. The harness uses reactive authentication (ADR-002). If the credential is invalid, the endpoint will return 401 and the harness will handle the failure cleanly.

## 6. On-Disk Artifacts

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

Per the ADR-004 amendment (2026-04-29 / 0.7.0), the ledger granularity is one entry per (model, flush-point) pair. A flush-point is the end of a `batch()` call (`flush_reason: "batch_end"`) or the close of the client (`flush_reason: "client_close"`). A model with zero calls since the last flush does not produce an entry. The accumulated counters reset after every flush, so each entry describes deltas since the previous flush rather than cumulative totals across the run.

```json
{
  "timestamp": "2026-04-29T14:23:11.412Z",
  "job_id": "my-batch_20260429T142300Z",
  "job_name": "my-batch",
  "project": "my-project",
  "model": "claude-sonnet-4-5-20241022",
  "total_calls": 7,
  "successful_calls": 7,
  "failed_calls": 0,
  "success_rate": 1.0,
  "total_tokens_in": 868,
  "total_tokens_out": 3584,
  "estimated_cost": 0.0,
  "duration_seconds": 12.4,
  "flush_reason": "batch_end"
}
```

A multi-rater batch produces one entry per model with nonzero calls, all sharing the same `job_id`, `job_name`, `timestamp`, `duration_seconds`, and `flush_reason`. A `complete()`-only session produces entries at `client_close` rather than `batch_end`; mixed `complete()`/`batch()` sessions produce one entry per model per flush, with `complete()` calls before a batch flushed at that batch's end.

The ledger is an estimation tool, not a billing-reconciliation artifact. Rates baked into each entry reflect the catalog values active at flush time; rate changes after a flush do not retroactively update historical entries. Consumers needing exact cost reconciliation should join against an external billing record.

The ledger is durable. Entries are flushed after each write. An interrupted run may be missing the lines that would have been written at the next flush-point; successful calls that completed before the previous flush are safe.

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

## 7. Error Types

All raised exceptions inherit from `UsaiHarnessError`.

- `ConfigurationError`: Invalid configuration or parameters. Caught at init.
- `AuthenticationError`: HTTP 401 or 403 from the provider. Raised by `complete()` or `batch()`. Preserves checkpoint. Provider endpoints differ in which HTTP status they return for an invalid API key. USAi returns 401 or 403, both of which raise `AuthenticationError` and halt the worker pool. Gemini's OpenAI-compat endpoint returns 400 with a structured error body, which the harness treats as a per-call non-retryable failure rather than an auth halt. See `docs/ops-guide.md` section 7.1 for the operational implications and the recommended pre-flight mitigation.
- `TransportError`: Network failure, DNS issue, TLS error, or provider error not covered by retry.
- `RateLimitError`: Sustained rate-limit failure after adaptive backoff exhausts. Rare; usually indicates a misconfiguration or provider outage.
- `ModelNotFoundError`: Requested model is not in the provider's current catalog. Run `discover-models` to refresh.
- `CheckpointError`: Checkpoint file is corrupt or inconsistent with the task list. Delete the checkpoint and restart, or investigate.

Every exception carries a human-readable message and, where applicable, a `.context` dict with the provider, model, task_id, and relevant HTTP status for diagnostic use.

## 8. Deprecation Policy

Public API additions follow semantic versioning. Deprecated functions emit `DeprecationWarning` for at least one minor version before removal. Configuration schema changes do the same: an old-format config loads with warnings for a full minor-version cycle before being rejected.

Private modules and internal helpers (anything prefixed with `_` or documented as internal) can change without notice. Do not import them.
