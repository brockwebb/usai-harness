# Test, Evaluation, Verification, and Validation Plan — usai-harness

**Version:** 1.2
**Date:** 2026-04-26
**Status:** Audited (Tasks 06-14 reflected; CI workflow live)

## 1. Purpose

This document describes how the usai-harness is tested and verified. It establishes which requirements are verified by which methods, what evidence is produced, and how that evidence is preserved for audit. Conformance to the SRS and NFR is established by the activities in this plan.

The harness is infrastructure: a rate-limited, credentialed, logged client for calling OpenAI-compatible LLM endpoints. It is not an AI system, not a model, and not a statistical product. Accordingly, TEVV for the harness follows software engineering practice. The harness does participate in the evaluation of *other* artifacts built on top of it; that participation is addressed in Section 7 (Evidence Artifacts for Downstream Evaluation).

## 2. Scope

This plan covers:

- Unit tests of individual modules in `usai_harness/`.
- Integration tests against live LLM endpoints.
- Security verification for SEC requirements in the SRS and NFR-S requirements in the NFR.
- Performance and reliability verification for NFR-P and NFR-R requirements.
- Operational verification via the `usai-harness audit` command.
- The role of harness-produced artifacts (call log, cost ledger, reports) as evidence for downstream workload evaluation.

Out of scope:

- Evaluation of LLM outputs returned by providers. Output quality is a workload concern, handled by the calling project.
- Evaluation of provider infrastructure (USAi, OpenRouter, Azure OpenAI). Provider accreditation is independent.
- Model-level bias, fairness, or accuracy testing. The harness has no outputs that carry these properties.

## 3. Verification Methods

Four methods are used, selected per requirement based on what establishes conformance most efficiently.

**M-1: Unit test.** Automated pytest suite exercises a single module or function in isolation. Used for logic that can be verified deterministically without a live endpoint.

**M-2: Integration test.** Automated or semi-automated test against a live LLM endpoint. Used for behaviors that depend on real network, real auth, or real provider responses.

**M-3: Inspection.** Manual review of code, configuration, or output. Used for structural properties (no `yaml.load` call in the codebase, ledger dataclass has no content field) where a test would be more complex than the inspection.

**M-4: Demonstration.** Running the harness through a realistic scenario and observing the outcome. Used for end-to-end properties (setup walkthrough, checkpoint-and-resume, `usai-harness audit` output) that are verified by the workflow succeeding.

## 4. Test Strategy by Layer

### 4.1 Unit Tests

Each module in `usai_harness/` has a dedicated test file in `tests/`. Unit tests run offline and complete in under thirty seconds as a suite.

| Module | Test file | Focus |
|--------|-----------|-------|
| `client.py` | `test_client.py` | Wiring, lifecycle, context management, model echo, log_content opt-in. Mocks transport, credentials, workers. |
| `config.py` | `test_config.py` | Config loading, schema validation, provider/model resolution, live catalog merge with drop warning, error_body_snippet_max_chars validation. |
| `key_manager.py` | `test_key_manager.py` | CredentialProvider protocol. Each provider backend (dotenv, envvar, azure) with mocked sources. Per-OS user_config_env_path resolution. Factory dispatch. |
| `transport.py` | `test_transport.py` | Transport contract conformance. HttpxTransport with mocked httpx client. TLS-verify warning. Error body snippet capture, redaction, truncation, binary skip, body-read failure. |
| `redaction.py` | `test_redaction.py` | Bearer / *_API_KEY / sk- token scrubbing. Recursive dict/list/tuple walk. No mutation of inputs. |
| `rate_limiter.py` | `test_rate_limiter.py` | Token bucket math, adaptive rate adjustment, floor and ceiling. |
| `worker_pool.py` | `test_worker_pool.py` | Task distribution, retry, AuthHaltError on 401/403, deferred-task preservation. |
| `logger.py` | `test_logger.py` | JSONL format, redaction, flush-per-write, content opt-in, error_body presence/omission. |
| `cost.py` | `test_cost.py` | Ledger format, rate application, aggregation, structural absence of content field on `LedgerEntry`. |
| `report.py` | `test_report.py` | Summary computation, model-mismatch detection, backward-compat fallback for legacy `model` field. |
| `setup_commands.py` | `test_setup_commands.py` | init / add-provider / discover-models / verify / ping handlers. URL composition. AST guard against `input()` for keys. |
| `audit_command.py` | `test_audit.py` | Gitignore coverage check, tracked-secret scan, pip-audit soft fallback. |
| `cli.py` | `test_cli.py` | Argparse dispatch routing for every subcommand. |
| repo hygiene | `test_repo_hygiene.py` | `requirements.lock` exists and contains hash pins. |

Unit test coverage target: 80 percent for modules other than `transport.py`. `transport.py` is exercised primarily by integration tests because most of its behavior depends on live HTTP semantics.

Current unit-test count at audit time (Tasks 06-10 reflected): 208 tests passing across 14 test files, including 9 redaction tests, 11 CLI dispatcher tests, 23 setup-command tests, 7 audit tests, and 2 repo-hygiene checks added during the alignment sweep.

### 4.2 Integration Tests

Integration tests run against a live LLM endpoint. They require a valid API key and outbound HTTPS access. They are not run in CI by default because they cost money, require credentials, and depend on external availability.

Integration test suite at `tests/integration/`. Entry point: `python tests/integration/test_live_usai.py`. The runner is a standalone Python script (not a pytest target) that executes 11 numbered checks against the configured default provider:

1. `client_initializes` — credential resolves, provider config loaded, base URL extracted.
2. `single_completion` — one chat-completion call returns OpenAI-format body with usage tokens.
3. `system_prompt` — system prompt is honored.
4. `temperature_deterministic` — `temperature=0.0` produces identical outputs across two calls (WARN when the model is non-deterministic at 0).
5. `small_batch` — 5-task batch completes through the worker pool with non-zero latencies.
6. `log_file_written` — the per-run JSONL log exists and every entry has `timestamp`, `task_id`, `model_requested`, `status_code`.
7. `cost_ledger_written` — `cost_ledger.jsonl` has at least one entry with the required fields.
8. `post_run_report` — `generate_report` and `format_report` succeed against the live log.
9. `throughput_within_bounds` — observed throughput is within USAi's 3/sec ceiling and above 0.5/sec.
10. `bad_model_graceful` — a bogus model ID produces a graceful error, not an unhandled exception.
11. `auth_halt_on_rotated_key` — a deliberately invalid key triggers `AuthHaltError` (PASS) when the endpoint returns 401/403, or WARN when it returns another status code (e.g., Gemini's 400; see ops-guide §7.1).

Status (current): the suite has been written and validated end-to-end against Google's OpenAI-compat endpoint as part of the Task 08 Gemini smoke test. It has not yet been executed against a live USAi endpoint; that run is gated on USAi key availability. The Gemini run surfaced and documented one provider-specific divergence (test 11 returns WARN for Gemini because Google returns HTTP 400, not 401/403, on invalid keys).

Results are captured to `tests/integration/logs/` with per-run call log and cost ledger, plus the pass/warn/fail summary printed by the runner.

### 4.3 Security Tests

Security tests verify SEC requirements and NFR-S quality attributes.

| Requirement | Verification | Method |
|-------------|--------------|--------|
| SEC-001 secret redaction | `test_redaction.py` exercises the scrubber; `test_transport.py::test_error_body_*` confirms boundary-enforced redaction; integration runner step 7 greps the call log for known patterns. | M-1 (primary), M-2 (live confirmation) |
| SEC-002 yaml.safe_load only | Grep `usai_harness/` for `yaml.load(` outside the safe path. | M-3, manual + recurring |
| SEC-003 TLS verification | `test_transport.py::test_tls_verify_disabled_warns_per_call` and `test_tls_verify_default_silent`. | M-1 |
| SEC-004 no secrets in config files | Inspect `configs/models.yaml` schema; `audit` regex flags any tracked-file leak. | M-3 |
| SEC-005 gitignore coverage | `test_audit.py::test_gitignore_*`. | M-1 |
| SEC-006 hash-pinned install | `test_repo_hygiene.py::test_requirements_lock_*` plus `.github/workflows/ci.yml` `lockfile_install` job. | M-1, M-4 |
| NFR-S-001 no secrets at rest | `test_redaction.py::*`, transport error-body redaction tests, integration runner step 7. | M-1 (primary), M-2 (live) |
| NFR-S-002 .gitignore coverage | `test_audit.py::test_gitignore_*`. | M-1 |
| NFR-S-003 YAML attack surface | Attempt YAML with `!!python/object` constructor, verify rejection. | M-1 |
| NFR-S-004 dependency auditability | `.github/workflows/ci.yml` `audit` job runs `pip-audit` advisory-only with findings written to the job summary on every push. | M-4 |
| NFR-S-005 lockfile install | `.github/workflows/ci.yml` `lockfile_install` job verifies `pip install --require-hashes -r requirements.lock` plus a hard-deps-only smoke import. | M-4 |

### 4.4 Performance Tests

Performance tests verify NFR-P requirements. They require a live endpoint.

| Requirement | Test | Acceptance |
|-------------|------|------------|
| NFR-P-001 rate-limited throughput | Ten-minute batch against USAi, measure completed calls. | Within 10 percent of 3/sec ceiling after safety margin. |
| NFR-P-002 batch overhead | Loop of calls against low-latency mock endpoint. | Median overhead below 50 ms per call. |
| NFR-P-003 worker scaling | Sweep worker count 1, 2, 3, 4, 5 at same rate limit. | Throughput rises 1→3, plateaus 3→5. |

Results logged to `tests/performance/results/{timestamp}/`.

### 4.5 Reliability Tests

Reliability tests verify NFR-R requirements. They require mechanisms for injecting faults.

| Requirement | Test | Acceptance |
|-------------|------|------------|
| NFR-R-001 transient error recovery | Batch against mock that returns 10 percent 5xx responses. | Batch completes with all successful results. |
| NFR-R-002 checkpoint durability | Kill process mid-batch with SIGKILL, resume. | No task re-executed, no task lost. |
| NFR-R-003 ledger durability | Same interruption test, compare ledger entries to successful calls. | One entry per successful call, exactly. |
| NFR-R-004 fail-fast on unrecoverable | Mock returns 401 mid-batch. | Pool halts within one second, remaining queue not processed. |

### 4.6 Usability and Documentation Tests

| Requirement | Verification | Method |
|-------------|--------------|--------|
| NFR-U-001 clear failure messages | Walk each error path, inspect message content. | M-3 |
| NFR-U-002 CLI discoverability | `usai-harness --help` and each subcommand help. | M-1 |
| NFR-U-003 documentation completeness | Cross-check SRS against README, API reference, ops guide. | M-3 |

## 5. Requirements Traceability

Every FR, SEC, IR, and NFR in the SRS and NFR documents is traced to:

1. The implementing module or configuration.
2. The test case that verifies it.
3. The verification method.
4. The evidence artifact produced on pass.

Traceability is maintained in the Requirements Traceability Matrix at `docs/rtm.md`. The RTM is updated whenever requirements are added or modified, and when tests are added or modified. The RTM is the audit-ready view of conformance.

## 6. Test Environment

Unit tests run in any Python 3.12+ environment with the dev extras installed:

```bash
pip install -e ".[dev]"
pytest
```

Integration tests require additionally:

- A `.env` file with `USAI_BASE_URL` and `USAI_API_KEY`, or equivalent configuration for another provider.
- Outbound HTTPS to the configured provider.
- A budget allowance for call costs (when applicable).

Performance and reliability tests require additionally:

- A fault-injection harness at `tests/perf/mock_server.py` (OpenAI-compatible mock with configurable latency, error rates, rate limits).

Continuous integration runs:

- Unit test suite on every push.
- `pip-audit` on every push.
- Security lint (grep for `yaml.load(`, scan for committed secrets) on every push.
- Install-from-lockfile test weekly.

Integration, performance, and reliability tests are run manually before each release and archived under `tests/*/results/`.

## 7. Evidence Artifacts for Downstream Evaluation

The harness produces artifacts that downstream workload evaluation consumes. These artifacts are not TEVV subjects for the harness itself; they are TEVV *outputs* of the harness that feed TEVV for projects that use it.

Three artifacts are produced by default and designed for audit use:

**The call log at `logs/calls.jsonl`** contains one entry per call with timestamp, project, job, task ID, model requested, model returned, status, latency, token counts, and error category. No content by default. This artifact supports reproducibility claims for any workload that uses the harness.

**The cost ledger at `cost_ledger.jsonl`** is append-only and contains per-call token counts, rates applied, and computed cost. No content, by structural guarantee. This artifact supports cost audit and usage reporting for any workload.

**The post-run report** produced at the end of each batch summarizes call count, success rate, tokens, cost, observed rate-limit behavior, and model-echo mismatches. Researchers include this in their project documentation.

A project using the harness inherits documentation-grade evidence for transparency, auditability, and reproducibility without additional instrumentation. Downstream evaluation frameworks that require such evidence (for example, FCSM 20-04 transparency dimensions or NIST AI RMF documentation subcategories, when applied to the *workload* built on the harness) can cite these artifacts directly.

This relationship is explicit. The harness is not evaluated under FCSM or NIST AI RMF. Projects built using the harness are evaluated, and the harness makes their evaluation easier.

## 8. Acceptance Criteria

The harness is considered conformant when:

1. All unit tests pass.
2. All integration tests have been run at least once against a live endpoint within the last thirty days, with results archived.
3. All security tests pass.
4. Performance tests demonstrate conformance to NFR-P acceptance criteria.
5. Reliability tests demonstrate conformance to NFR-R acceptance criteria.
6. The RTM shows coverage for every requirement in the SRS and NFR.
7. `pip-audit` reports no known high-severity vulnerabilities in the dependency set.
8. Documentation (README, SRS, NFR, Architecture, API Reference, Ops Guide) is consistent with the implemented behavior.

A release that fails any of these criteria is not marked as a stable version. A release may be published as a pre-release with known gaps documented in the release notes.

## 9. Maintenance

This plan is reviewed whenever:

- Requirements are added or modified in the SRS or NFR.
- A new module is added to the package.
- A new credential backend or transport is added.
- A new CLI subcommand is added.
- A dependency is added, removed, or bumped by a major version.

Review outcomes update both this document and the RTM in the same change.
