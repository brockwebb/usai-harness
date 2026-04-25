# ADR-009: Setup Ergonomics and Endpoint as Source of Truth for Models

**Status:** Accepted
**Date:** 2026-04-24

## Context

First-run experience is the make-or-break moment for a library researchers will share. If setup requires editing multiple files, knowing the correct model identifier strings in advance, or reading documentation before writing a single line of code, adoption stalls.

Two specific pain points surfaced during initial use:

First, the shipped `configs/models.yaml` contained placeholder model identifiers that did not match what USAi actually expects. The first call failed with an opaque model-not-found error. The working identifiers were available in a companion tool (`usai-api-tester`), but the harness did not know that.

Second, there is no graceful path for adding a new provider. The user is expected to know where to put the key, what the base URL is, and which model identifiers are valid.

Both problems share a root cause: the local configuration is treated as the source of truth for information that belongs to the endpoint. Model identifiers change when providers update their catalogs. Base URLs vary per environment. Keys rotate. A static config file cannot be kept accurate against a moving target.

The companion tool already solved this at small scale. It queries `/api/v1/models` on startup and uses the live response as the source of truth, with local config providing presentation overrides only (friendly names, temperature ranges).

## Decision

Adopt the same pattern in the harness. Add CLI commands that handle setup through the endpoint rather than through manual file editing.

### Principles

1. **The endpoint is the source of truth for model identity.** Local configuration supplies presentation and defaults (display names, temperature ranges, cost rates) and never asserts which models exist.
2. **Setup is interactive where it needs to be.** First-run captures credentials via prompt, writes them to the user-level location specified in ADR-008, and verifies end-to-end before reporting success.
3. **Setup is idempotent.** Running `init` or `verify` twice produces the same result as running them once. No accumulated state, no partial configurations.

### Commands

**`usai-harness init`** — First-run setup. Prompts for provider name (default `usai`), base URL, and API key. Writes to user-level `.env`. Calls `/api/v1/models` to retrieve live model list. Writes verified model list to user-level config. Executes one test completion against a default model. Reports success or the specific failure. Idempotent against re-run.

**`usai-harness add-provider <name>`** — Register an additional provider (OpenRouter, Anthropic via OpenAI-compatible shim, another agency gateway). Prompts for base URL and key, tests the endpoint, updates the model list. Uses the same user-level storage.

**`usai-harness discover-models [provider]`** — Refreshes the model list for the named provider (or all providers if omitted) by querying each endpoint. Rewrites the model list in the user-level config. Does not touch credentials.

**`usai-harness verify`** — End-to-end check of every configured provider. For each, verifies the credential resolves, the endpoint is reachable, `/api/v1/models` returns a list, and a test completion against the default model succeeds. Reports per-provider pass/fail. Supersedes the earlier `ping` command as the complete health check.

**`usai-harness ping`** — Retained as a minimal single-call check against the default provider. Useful as a fast sanity check before launching a long-running batch job. `verify` is the full check; `ping` is the quick one.

### Security details

Key capture uses `getpass.getpass()`, not `input()`. Keys are not echoed, not added to shell history in pastes, and not left in terminal scrollback. Applies to `init` and `add-provider`.

Setup commands respect the credential backend selected in project configuration. `init` is meaningful for `DotEnvProvider`. For `EnvVarProvider`, `init` reports that credentials come from environment variables and no file action is needed. For `AzureKeyVaultProvider`, `init` verifies the vault URL and secret name but does not write credentials (Azure manages them).

### Model configuration schema

Local `configs/models.yaml` declares providers, their base URLs, the environment variable name for their keys, and optional presentation overrides per model. The live model list retrieved from each endpoint is merged at runtime. If an entry in the live list matches a local override by ID, the override's friendly name and temperature settings apply. If not, the model ID is used as the display name.

The model list written by `init` and `discover-models` is stored in the user-level config directory alongside the `.env`, not in the harness package source tree. Refreshing it does not modify the repository.

## Consequences

The defect that motivated this ADR disappears structurally. The harness cannot ship wrong model slugs because model slugs come from the endpoint at setup time, not from a checked-in configuration file.

Onboarding drops to one command. A researcher installing the harness runs `usai-harness init`, answers two prompts, and has a working setup verified against the real endpoint. Five minutes, no documentation reading required to clear the first hurdle.

Additional providers are cheap to add. One command, one prompt pair, one `discover-models` call. No hand-editing of YAML.

Model catalog drift is handled operationally. When a provider updates its catalog, the researcher runs `usai-harness discover-models` and the harness picks up the change. No code changes, no pull request, no new release.

The configuration file at `configs/models.yaml` in the repository becomes seed content for unfamiliar providers and a place for presentation overrides researchers want to share. It is no longer the authoritative list of model IDs. Calling projects that depend on model IDs from the live list remain robust to provider changes.

`usai-harness verify` becomes the command a researcher runs before starting a weekend batch job. Combined with the note in the README about checking key lifetime, it covers the Monday-morning-whomp-whomp case.

The `audit` command from ADR-007 and the setup commands from this ADR together form the operational CLI. `init` gets you running. `verify` confirms readiness. `discover-models` refreshes the catalog. `audit` checks security hygiene. `ping` is the thirty-second smoke test.

## Amendment, 2026-04-24 — Provider credential field split

Implementation note (not a new architectural decision): the `providers:` block carries one credential reference per entry. For the `dotenv` and `env_var` backends, that reference is `api_key_env`, naming an environment variable. For the `azure_keyvault` backend, it is `api_key_secret`, naming a Key Vault secret. A provider entry may set both when it supports multiple backends.

The original implementation overloaded `api_key_env` for both meanings; the field name lied for the Azure case. This was caught early and corrected. To preserve existing user catalogs, the Azure backend accepts `api_key_env` as a deprecated fallback in 0.1.x with a `DeprecationWarning` directing users to rename. The fallback is removed in 0.2.0.

The architectural decision recorded above is unchanged. The endpoint remains authoritative for model identity; backends still differ only by where they fetch the credential from.
