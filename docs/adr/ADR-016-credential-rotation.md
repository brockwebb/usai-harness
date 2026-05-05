# ADR-016: Dual-Path Credential Rotation

**Status:** Accepted
**Date:** 2026-04-30

## Context

ADR-002 fixes the per-call credential resolution and the auth-halt contract: a 401 or 403 from the endpoint stops the worker pool within 1 second and raises `AuthHaltError` carrying the failing task's id, status, and body. Per ADR-002 the harness does not track expiry — the endpoint is the source of truth. Per ADR-008 the user-level `.env` lives at a per-OS config path so one rotation covers every project on the machine.

What ADR-002 does not specify is what happens after the halt. The harness raises, the user sees a stack trace and a status code, the workload aborts, and the user is on their own to find the env file, edit it, and re-run from scratch. The friction surfaced on the work machine during 0.7.0 bootstrap: the user knew the credential was the problem, but had to remember the path (`~/.config/usai-harness/.env` on Linux/macOS, `%APPDATA%\usai-harness\.env` on Windows), open it, find the right variable name, and edit it by hand. None of that is a hard problem — it is the kind of small friction that adds up across daily use.

A second related friction surfaced in the same session: there is no proactive path. When an organization rotates a credential on a schedule, or a user receives a fresh key from the issuing system, there is no command to update it. The user has to either trigger an auth halt to get any rotation experience at all, or fall back to manual editing.

Both frictions point at the same gap: credential rotation has no first-class affordance.

## Decision

Two paths, sharing one underlying primitive.

### Path A — Automatic recovery on auth halt

When `USAiClient.batch()` or `USAiClient.complete()` sees an `AuthHaltError` (or, for `complete()`, a 401/403 directly from the transport), the harness checks whether stdin is interactive. If yes, it prompts the user for a fresh key with masked input, writes the new key to the user-level `.env` under the provider's `api_key_env` variable, refreshes the in-process api_key cache, and resumes the workload. For `batch()`, only tasks that did not complete before the halt are re-run; successful results from before the halt are kept. For `complete()`, the failing call is retried once with the new key.

The recovery prompt fires at most once per workload. A second consecutive 401 means the new key is also bad; looping the prompt would let a confused user paste the same bad key several times before realizing the endpoint or the issuing system is the problem. Re-raising the `AuthHaltError` after the first failed retry surfaces the failure cleanly.

In non-TTY contexts (CI, piped stdin, scripted runs), recovery is skipped — `is_interactive()` returns False — and the harness retains the ADR-002 halt-and-raise behavior. CI runs do not block on stdin.

The recovery hook is dotenv-only. `AzureKeyVaultProvider` rotation happens in the vault, not in the harness; auto-recovery against an Azure-backed project is a no-op (returns False from `_try_recover_credential`) and the original auth halt re-raises.

### Path B — Manual `usai-harness set-key`

For the proactive case: the user knows a rotation is happening and wants to update the credential without triggering an auth halt first.

`usai-harness set-key [--provider NAME]` (default `--provider usai`) validates that the named provider exists in the user-level catalog, prompts for the new key (masked), persists it to the user-level `.env`, and optionally tests the new key against the provider's `/models` endpoint. The save is unconditional once the prompt succeeds; a failed connectivity test prints a stderr warning and exits 0 (the key is still saved). Unknown provider, empty key, or an Azure-style entry (no `api_key_env`) exit 1 without writing.

Path B is independently valuable. A user can rotate proactively before any workload runs, or after a halt to update the key for the next session. The two paths share the `_write_env_var` upsert and the `_masked_input` prompt helper but have distinct entry points.

### Both paths

The user never needs to know where the `.env` file lives, what variable name the key is stored under, or what the endpoint URL is. The harness handles all of that through the user-level catalog and the per-OS path helpers from ADR-008.

The new key is never logged or echoed. Path A prints `"New key saved."` and `"Resuming workload from task <id>."` Path B prints `"New key saved for <provider>."` plus the optional connectivity test result. The masked-input helper writes only `*` characters to the terminal during typing.

### Rejected alternatives

- **Auto-only.** Leaves no path for proactive rotation; users would be forced to trigger an auth halt to update a key they already know is changing.
- **Manual-only.** Requires the user to remember the command exists at the moment a workload halts mid-run. Most users will not.
- **Silent retry with cached key.** Nonsensical: the cached key is what failed.
- **Config flag for auto-recovery.** Adds surface area without adding capability. The right gate is `stdin.isatty()`, which is already correct.
- **`recover_stale_credential` writes to project-local `.env` if present.** Rejected: the harness should not modify project-committed config files. If a project-local `.env` shadows the user-level rotation, the in-process cache is set directly to the new key for the rest of the session and the user gets a working retry; future sessions need the project-local file resolved by the user.

## Consequences

A user whose key expires mid-batch sees a single masked prompt, pastes a fresh key, and the workload resumes from the failing task. No state is lost. No command needs to be remembered. The cost ledger continues to record per-(model, flush-point) entries normally; the recovery does not produce duplicate entries.

A user who knows a rotation is happening runs `usai-harness set-key`, pastes the new key, sees `"New key saved for usai."` plus optionally `"OK: catalog has N models."`, and continues. No editor, no path lookup.

`AzureKeyVaultProvider` users are unaffected by either path. Vault rotation happens in the vault. The harness's behavior on auth halt against an Azure-backed project remains the ADR-002 raise.

The implementation surface is contained: one new module (`auth_recovery.py`), two new entry points in `client.py` and `cli.py`, and one new SRS section. No changes to `key_manager.py`, no changes to `worker_pool.py` (the existing `WorkerPool.results` property already exposes pre-halt results), no changes to ADR-002 itself. ADR-002's contract is unchanged; this ADR layers a recovery flow on top.

The dual-path design means each path is independently testable and independently valuable. Path A tests run with mocked recovery callbacks and verify the workload resumption; Path B tests run with mocked prompts and verify the upsert and optional connectivity test. The shared primitives (`_write_env_var`, `_masked_input`, `_fetch_models`) already have their own coverage from ADR-013-era tests.
