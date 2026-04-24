# Non-Functional Requirements — usai-harness

**Version:** 1.0
**Date:** 2026-04-24
**Status:** Baseline

## 1. Purpose

This document specifies quality attributes the usai-harness must exhibit. Functional behavior is specified in the SRS. Each NFR has an acceptance criterion and a verification method so conformance can be established objectively.

## 2. Performance

**NFR-P-001: Rate-limited throughput.**
Against a provider enforcing 3 requests per second, the harness shall sustain throughput within 10 percent of the rate-limit ceiling over a 10-minute window, not counting retry overhead. The 10 percent margin accounts for the safety margin specified in FR-018 and for clock drift.
*Verification:* Integration test against USAi or equivalent. Measure completed calls over a 10-minute window and compare to the rate-limit ceiling.

**NFR-P-002: Batch overhead.**
The harness shall introduce no more than 50 milliseconds of median latency per call beyond the provider's own round-trip time. This covers queuing, rate-limiter checks, logging, and ledger writes.
*Verification:* Integration test measuring end-to-end latency against a low-latency mock endpoint.

**NFR-P-003: Concurrent worker scaling.**
Increasing the worker pool size from 1 to 3 shall increase throughput measurably, within the bounds set by the rate limiter. Increasing beyond 3 shall not produce further gains at USAi's current rate limit.
*Verification:* Integration test sweeping worker count from 1 to 5.

## 3. Reliability

**NFR-R-001: Transient error recovery.**
The harness shall complete batch jobs successfully in the presence of transient provider errors (HTTP 5xx, network timeouts, isolated 429s) at rates up to 10 percent of total calls, using the retry policy defined in FR-021.
*Verification:* Integration test with injected transient failures at configurable rates.

**NFR-R-002: Checkpoint durability.**
Checkpoint state shall survive a kill signal (SIGKILL, SIGTERM) at any point during batch execution. Resume after interruption shall not re-execute completed tasks.
*Verification:* Integration test that kills the process mid-batch and verifies resume correctness.

**NFR-R-003: Ledger durability.**
Every successfully completed call shall produce exactly one ledger entry. No call shall produce multiple entries. No completed call shall be missing from the ledger.
*Verification:* Integration test that compares ledger entry count to successful-call count across a batch with injected interruptions.

**NFR-R-004: Fail-fast on unrecoverable errors.**
Authentication failures, configuration errors, and unrecoverable transport errors shall halt execution immediately rather than exhausting retry budgets. The worker pool shall stop accepting new tasks within one second of detecting such an error.
*Verification:* Integration test with injected 401 responses.

## 4. Security

**NFR-S-001: No secrets at rest in logs.**
No file written by the harness (call log, cost ledger, error log, report output) shall contain plaintext API keys, bearer tokens, or credential material.
*Verification:* Test that injects known key patterns into calls and greps output files. Recurring as part of CI.

**NFR-S-002: No secrets in version control.**
The default `.gitignore` shall cover all files that may contain secrets or call content. The `usai-harness audit` command shall verify this coverage.
*Verification:* Unit test against the bundled gitignore. Manual verification via audit command.

**NFR-S-003: Bounded attack surface via YAML.**
The config loader shall refuse inputs that would be accepted by `yaml.load` but not by `yaml.safe_load`.
*Verification:* Unit test with YAML constructors that trigger code execution under `yaml.load`.

**NFR-S-004: Dependency auditability.**
Each hard dependency shall have a published version history, a public source repository, and a maintained CVE record. New hard dependencies may not be added without review.
*Verification:* Manual review during dependency change. `pip-audit` in CI.

**NFR-S-005: Reproducible install.**
The repository shall support `pip install -r requirements.lock --require-hashes` to reproduce the audited dependency set exactly.
*Verification:* CI job that installs from the lockfile and runs the test suite.

## 5. Portability

**NFR-PO-001: Python version support.**
The harness shall run on Python 3.12 and higher. The development target is 3.14.
*Verification:* CI matrix across supported Python versions.

**NFR-PO-002: Operating system support.**
The harness shall run on Linux, macOS, and Windows. Platform-specific code paths shall be avoided.
*Verification:* CI matrix across supported operating systems.

**NFR-PO-003: Restricted-environment install.**
The harness shall install in environments that permit only `httpx`, `python-dotenv`, and `pyyaml` from their approved package set. Optional extras may be unavailable in such environments without affecting core functionality.
*Verification:* Install test with only the three hard dependencies present.

**NFR-PO-004: Endpoint portability.**
The same harness code shall call USAi, OpenRouter, and Azure OpenAI without modification, given appropriate configuration.
*Verification:* Integration tests against each provider.

## 6. Maintainability

**NFR-M-001: Module independence.**
Each module in `usai_harness/` shall have its own test file. Modules other than `client.py` shall be usable and testable without importing `client.py`.
*Verification:* Import graph inspection. Test coverage review.

**NFR-M-002: Test coverage.**
Unit test coverage shall be at least 80 percent for modules other than `transport.py`. The transport layer is exercised by integration tests against live endpoints.
*Verification:* Coverage report in CI.

**NFR-M-003: No hidden state.**
The harness shall not rely on global state beyond what is explicitly constructed in the client. A second `USAiClient` instance in the same process shall not interfere with a first.
*Verification:* Unit test with two concurrent clients.

**NFR-M-004: Configuration over code.**
Provider, model, rate-limit, and credential configuration changes shall not require code changes. New providers and models shall be added by editing `configs/models.yaml`.
*Verification:* Walkthrough: add a hypothetical new OpenAI-compatible provider and verify no Python code needs editing.

**NFR-M-005: Dependency stability.**
Hard dependency versions shall not be upgraded casually. Major-version bumps of hard dependencies require documentation of the change rationale and a regression test pass.
*Verification:* Changelog review. `requirements.lock` diff review on each update.

## 7. Usability

**NFR-U-001: Clear failure messages.**
User-facing errors (bad config, missing credentials, auth failures, provider errors) shall include the error cause, the likely next action, and a pointer to relevant documentation where applicable. Stack traces alone are not sufficient.
*Verification:* Manual review of each error path during integration testing.

**NFR-U-002: CLI discoverability.**
`usai-harness --help` shall list all available subcommands with one-line descriptions. Each subcommand shall have its own `--help`.
*Verification:* Unit test that invokes help and inspects output.

**NFR-U-003: Documentation completeness.**
The README, API reference, and operations guide together shall cover all features specified in the SRS. No feature shall be discoverable only by reading source code.
*Verification:* Manual cross-check of SRS against documentation.

## 8. Acceptance Criteria Summary

An implementation conforms to this NFR document when every requirement above has been verified according to its stated verification method, and verification evidence is recorded in the Requirements Traceability Matrix.
