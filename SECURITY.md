# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository as the primary channel. Open the `Security` tab and choose `Report a vulnerability`. This keeps the report off public issue trackers until coordinated disclosure.

For situations where GitHub private vulnerability reporting is not available to the reporter, send a security-only report to `brock.s.webb@census.gov`. Do not use the public issue tracker for security findings.

Acknowledgment of receipt within seven days, initial assessment within thirty days. This is a single-maintainer project; faster guarantees would not be honest. CVE assignment and formal disclosure coordination are handled on a best-effort basis only and are not promised by default.

## Scope

In scope: any code under `usai_harness/`, the `usai-harness` CLI surface, configuration loading, credential handling, the redaction layer, and any artifact written to disk by the harness, including the call log, the cost ledger, and post-run reports.

Out of scope:

- Vulnerabilities in the Python interpreter itself.
- Vulnerabilities in upstream dependencies; report those to the upstream project. This project tracks dependency-level issues via `pip-audit`.
- Vulnerabilities in LLM provider endpoints (USAi, Gemini, OpenRouter, Azure, etc.); report those to the provider.
- Social engineering, phishing, and account takeover targeting maintainers or users.
- Denial-of-service against a user's own machine where the user controls the input.
- Physical attacks and side channels requiring local hardware access.

## What this project considers a vulnerability

Three categories.

Credential leakage paths are the most important. Any way the harness causes an API key, Bearer token, or Key Vault secret to appear in a log file, error message, traceback, console output, cost ledger entry, call log entry, post-run report, audit output, or any other on-disk artifact is a vulnerability. The redaction layer in `redaction.py` is supposed to prevent this at every output boundary; bypasses, regex gaps, and missed code paths all count.

Configuration loading paths that allow code execution from a crafted file are vulnerabilities. The harness uses `yaml.safe_load` precisely to prevent this, but any path through the configuration loader, environment-variable resolution, or live model catalog response that ends up evaluating arbitrary code is in scope.

Paths that allow bypassing intended rate limits, the auth-halt behavior, or the audit checks in a way that could be exploited to obscure activity from the call log or cost ledger are vulnerabilities. The cost ledger is intentionally append-only and metadata-only by design; any code path that allows writing prompts or response content to the ledger or that allows skipping a logged call qualifies.

## What this project does not consider a vulnerability

Some things look like security issues but are deliberate behaviors documented in the ADRs.

The harness logs error response bodies from non-2xx responses with redaction applied. This is a documented diagnostic feature in ADR-007 and is the only way the body of an endpoint-side rejection reaches the user. If you find a way to cause a redaction failure on those bodies, that IS a vulnerability under the credential-leakage category above. The body capture itself is not.

The harness allows users to disable TLS verification with a per-call stderr warning. This is intentional for operating against test endpoints with self-signed certificates and other internal validation scenarios. The visible warning on every call is the security boundary.

The harness writes prompts and responses to logs only when the user passes `log_content=True` per batch. Users opting in to content logging is a feature, not a vulnerability.

Provider endpoints occasionally return diagnostic information in error bodies, including request URLs, internal correlation identifiers, and rate-limit metadata. The harness logs these as-is after running them through the redactor. Information disclosure from a provider's error response is not a harness vulnerability.

## Supported versions

Currently only the latest 0.1.x release is supported with security patches. Older 0.1.x versions will not receive separate fixes; users should upgrade to the latest 0.1.x. Once 0.2.0 ships, the support policy will be reviewed and stated explicitly here.

## Public disclosure timeline

Default coordination window is ninety days from acknowledgment to public disclosure. Earlier disclosure is fine when a fix ships earlier and the reporter agrees. Reporters who request a longer embargo for actively exploited issues will be accommodated within reason; coordinate the extension at the time of report.
