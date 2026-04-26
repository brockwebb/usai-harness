# ADR-007: Security-by-Default Logging and Configuration

**Status:** Accepted
**Date:** 2026-04-24

## Context

The harness handles API keys, writes logs to disk, parses YAML configuration files, and makes HTTPS calls. Each of these operations has known failure modes when left on default-unsafe settings. Relying on users to configure safely puts the burden in the wrong place.

Federal environments additionally require security hygiene that survives the casual user. A developer who does not think about security should still not leak keys through error messages, should not execute arbitrary code through a crafted config file, and should not silently accept an untrusted TLS certificate.

## Decision

The following defaults are applied. None of them require user action to be effective. Each can be overridden intentionally, but safe behavior is the default.

### 1. Secret redaction in logs and error paths

A regex in `logger.py` and in the error-handling paths of `transport.py` scrubs `Bearer ...` tokens and any string matching the configured key pattern before writing to disk or emitting to stderr. Applies to call logs, error messages, and stack traces that the harness itself captures.

### 2. `yaml.safe_load` only

The config loader never calls `yaml.load`. This prevents a class of remote code execution via crafted YAML content. Enforcement is via lint and by direct inspection; there is one code path for loading YAML and it uses `safe_load`.

### 3. TLS verification enforced

The httpx transport uses default TLS verification. If a user sets `verify=False` on the transport, the harness emits a warning to stderr on every call, not once per session. The warning is intentionally noisy to prevent quiet habituation.

### 4. Content logging off by default

Reiterating from ADR-004: the call logger captures metadata by default. Prompt and response content is logged only when `log_content=True` is set intentionally per job.

### 5. Model echo check

Each call logs `model_requested` and `model_returned`. Mismatches are flagged in the post-run report. This catches endpoints silently routing to a different model, which can happen under provider-side failover or mis-routing.

### 6. Metadata-only cost ledger

Reiterating from ADR-004: the cost ledger structurally cannot contain content, because the ledger dataclass has no content field.

## Consequences

Accidental key leakage through logs, stack traces, and error messages is structurally reduced. A user does not need to remember to redact.

A crafted configuration file cannot execute code during parsing.

A misconfigured TLS verify setting is visible rather than silent, so it gets caught during development rather than in production.

Users retain control. Each default can be overridden when the situation requires it, but overrides are explicit choices, not accidents.

The `usai-harness audit` CLI subcommand (referenced in the SRS) checks gitignore coverage, scans for accidentally tracked secrets, and runs `pip-audit` against the current environment. It is the operational counterpart to these defaults: defaults prevent the common mistakes, the audit command catches the rest.

## Amendment, 2026-04-25 — Error body snippet logging

The original "log only what is needed" stance dropped non-2xx response bodies entirely. Task 04 made this conservative on the assumption that body content might leak credentials and that the redaction module had not been validated against real provider output. The Task 08 Gemini smoke test exercised boundary-enforced redaction in `redaction.py` against a real OpenAI-compat endpoint and confirmed that Bearer headers and provider-shaped key strings are scrubbed before any output reaches disk.

Task 10 reverses the body-drop. The transport now captures up to `error_body_snippet_max_chars` characters of the response body on non-2xx, passes the truncated text through `redact_secrets()`, and writes the result to the call log under `error_body`. Default is 200 characters; the cap is configurable up to 2000 via `configs/models.yaml`. Diagnostic value is high: Gemini's HTTP 400 on invalid keys carries the only useful information in the body, and the prior behavior dropped that signal silently. The change does not weaken the security posture because redaction now runs at every output boundary; future contributors who consider reverting this should first prove the redaction surface has regressed.
