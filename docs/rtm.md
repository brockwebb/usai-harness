# Requirements Traceability Matrix — usai-harness

**Version:** 1.0
**Date:** 2026-04-24
**Status:** Baseline

## 1. Purpose

This document traces every requirement in the SRS and NFR to its implementing module, verifying test, verification method, and source ADR. The RTM is the audit-ready view of conformance. It is updated whenever requirements, modules, or tests change.

## 2. How to Read This Matrix

**Requirement ID** — FR-nnn, SEC-nnn, IR-nnn (from SRS); NFR-P/R/S/PO/M/U-nnn (from NFR).

**Implementation** — The module or configuration that realizes the requirement.

**Test** — The specific test file, test case, or verification artifact that establishes conformance.

**Method** — One of M-1 (unit test), M-2 (integration test), M-3 (inspection), M-4 (demonstration). Defined in TEVV Plan Section 3.

**Source** — The ADR or principle that motivated the requirement.

A requirement without an implementation is not yet built. A requirement without a test is not yet verified. Both are visible at a glance in the status column.

## 3. Functional Requirements

### 3.1 Client Interface

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-001 | `client.py::USAiClient.complete` | `test_client.py::test_complete_*` | M-1, M-2 | Component contract | Implemented |
| FR-002 | `client.py::USAiClient.batch` | `test_client.py::test_batch_*` | M-1, M-2 | Component contract | Implemented |
| FR-003 | `client.py` task dict handling | `test_client.py::test_per_task_params` | M-1 | Component contract | Implemented |
| FR-004 | `client.py`, `logger.py`, `cost.py` | `test_logger.py::test_job_tag`, `test_cost.py::test_job_tag` | M-1 | ADR-004 | Implemented |
| FR-005 | `worker_pool.py` checkpoint logic | `tests/integration/test_live_usai.py::test_checkpoint_resume` | M-2 | ADR-002 | Implemented |

### 3.2 Credential Management

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-006 | `key_manager.py::CredentialProvider` | `test_key_manager.py::test_backend_selection` | M-1 | ADR-003 | Implemented |
| FR-007 | `key_manager.py` protocol definition | `test_key_manager.py::test_protocol_compliance` | M-1, M-3 | ADR-003 | Implemented |
| FR-008 | `configs/models.yaml` schema, `key_manager.py` | `test_config.py::test_per_provider_keys` | M-1 | ADR-003 | Implemented |
| FR-009 | `key_manager.py::AzureKeyVaultProvider`, `pyproject.toml` extras | `test_key_manager.py::test_azure_provider` | M-1 | ADR-003, ADR-005 | Planned |
| FR-009a | `key_manager.py::DotEnvProvider` resolution logic | `test_key_manager.py::test_resolution_order` | M-1 | ADR-008 | Planned |

### 3.3 Authentication Handling

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-010 | `key_manager.py` (absence of expiry state) | `test_key_manager.py::test_no_metadata_file` | M-1, M-3 | ADR-002 | Implemented |
| FR-011 | `worker_pool.py` halt logic, `client.py` error path | `tests/integration/test_live_usai.py::test_auth_failure_halt` | M-2 | ADR-002 | Implemented |
| FR-012 | `report.py::ping_cmd` | `test_report.py::test_ping_cli` | M-1, M-2 | ADR-002 | Planned |

### 3.4 Transport Layer

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-013 | `transport.py::HttpxTransport` | `test_transport.py::test_httpx_*` | M-1, M-2 | ADR-001 | Implemented |
| FR-014 | `transport.py::LiteLLMTransport`, `pyproject.toml` extras | `test_transport.py::test_litellm_*` | M-1 | ADR-001 | Planned |
| FR-015 | `transport.py::Transport` protocol | `test_transport.py::test_contract_compliance` | M-1, M-3 | ADR-001 | Implemented |
| FR-016 | `transport.py::HttpxTransport` | `tests/integration/test_live_usai.py::test_oai_compatibility` | M-2 | ADR-001 | Implemented |

### 3.5 Rate Limiting

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-017 | `rate_limiter.py::TokenBucket` | `test_rate_limiter.py::test_bucket_*` | M-1 | ADR-006 | Implemented |
| FR-018 | `configs/models.yaml` defaults | `test_config.py::test_usai_defaults` | M-1 | ADR-006 | Implemented |
| FR-019 | `rate_limiter.py` adaptive logic | `test_rate_limiter.py::test_adaptive_backoff` | M-1 | ADR-006 | Implemented |

### 3.6 Worker Pool

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-020 | `worker_pool.py::WorkerPool` | `test_worker_pool.py::test_pool_size` | M-1 | Component contract | Implemented |
| FR-021 | `worker_pool.py` retry logic | `test_worker_pool.py::test_retry_*` | M-1 | Component contract | Implemented |
| FR-022 | `worker_pool.py` halt logic | `test_worker_pool.py::test_fatal_halt` | M-1 | ADR-002 | Implemented |

### 3.7 Configuration

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-023 | `config.py::load_models` | `test_config.py::test_safe_load` | M-1, M-3 | ADR-007 | Implemented |
| FR-024 | `config.py::load_project_config` | `test_config.py::test_project_overrides` | M-1 | Component contract | Implemented |
| FR-025 | `config.py` validation | `test_config.py::test_validation_*` | M-1 | Fail-fast principle | Implemented |

### 3.8 Logging

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-026 | `logger.py::CallLogger` | `test_logger.py::test_jsonl_format`, `test_logger.py::test_flush` | M-1 | Component contract | Implemented |
| FR-027 | `logger.py` default entry schema | `test_logger.py::test_metadata_only_default` | M-1, M-3 | ADR-004, ADR-007 | Implemented |
| FR-028 | `logger.py` `log_content` flag | `test_logger.py::test_content_opt_in` | M-1 | ADR-004, ADR-007 | Implemented |
| FR-029 | `client.py`, `logger.py`, `report.py` | `test_logger.py::test_model_echo`, `test_report.py::test_mismatch_flag` | M-1, M-2 | ADR-007 | Implemented |

### 3.9 Cost Tracking

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-030 | `cost.py::CostTracker` | `test_cost.py::test_append_only` | M-1 | ADR-004 | Implemented |
| FR-031 | `cost.py::LedgerEntry` dataclass | `test_cost.py::test_no_content_field` | M-1, M-3 | ADR-004, ADR-007 | Implemented |
| FR-032 | `cost.py` rate recording | `test_cost.py::test_retroactive_compute` | M-1 | ADR-004 | Implemented |

### 3.10 Reporting

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-033 | `report.py::build_summary` | `test_report.py::test_summary_*` | M-1 | Component contract | Implemented |
| FR-034 | `report.py::cost_report_cmd` | `test_report.py::test_cost_report_cli` | M-1 | Component contract | Implemented |
| FR-035 | `report.py::audit_cmd` | `test_report.py::test_audit_*` | M-1, M-4 | ADR-007 | Planned |

### 3.11 Setup and Model Discovery

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-036 | `report.py::init_cmd` (or new `setup.py`) | `test_setup.py::test_init_*` | M-1, M-4 | ADR-009 | Planned |
| FR-037 | `report.py::add_provider_cmd` (or new `setup.py`) | `test_setup.py::test_add_provider_*` | M-1, M-4 | ADR-009 | Planned |
| FR-038 | `report.py::discover_models_cmd` (or new `setup.py`) | `test_setup.py::test_discover_*` | M-1, M-2 | ADR-009 | Planned |
| FR-039 | `report.py::verify_cmd` (or new `setup.py`) | `test_setup.py::test_verify_*` | M-1, M-2 | ADR-009 | Planned |
| FR-040 | `config.py` model list merge logic | `test_config.py::test_live_catalog_precedence` | M-1 | ADR-009 | Planned |
| FR-041 | Setup command key capture | `test_setup.py::test_getpass_used` | M-1, M-3 | ADR-009 | Planned |

## 4. Security Requirements

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| SEC-001 | `logger.py` redaction, `transport.py` error paths | `test_logger.py::test_redaction`, `tests/integration/test_live_usai.py::test_no_key_in_logs` | M-1, M-2 | ADR-007 | Implemented |
| SEC-002 | `config.py` uses `yaml.safe_load` only | `test_config.py::test_yaml_safe_only`, CI lint | M-1, M-3 | ADR-007 | Implemented |
| SEC-003 | `transport.py::HttpxTransport` TLS default, warning on verify=False | `test_transport.py::test_tls_verify_warning` | M-1 | ADR-007 | Implemented |
| SEC-004 | `configs/models.yaml` schema (no secret fields) | `test_config.py::test_no_secrets_in_config` | M-3 | ADR-003 | Implemented |
| SEC-005 | `.gitignore`, `report.py::audit_cmd` | `test_report.py::test_audit_gitignore` | M-3, M-4 | ADR-007 | Planned |
| SEC-006 | `requirements.lock` at repo root | CI job: install with `--require-hashes` | M-4 | ADR-005, ADR-007 | Planned |

## 5. Interface Requirements

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| IR-001 | `usai_harness/__init__.py` exports | `test_client.py::test_public_api` | M-1, M-3 | SRS Section 6 | Implemented |
| IR-002 | `pyproject.toml` console script | `test_report.py::test_cli_entry_point` | M-1 | SRS Section 6 | Implemented |
| IR-003 | `configs/models.yaml` schema, `config.py` validation | `test_config.py::test_schema_*` | M-1, M-3 | SRS Section 6 | Implemented |
| IR-004 | `config.py` project config validation | `test_config.py::test_project_schema` | M-1 | SRS Section 6 | Implemented |

## 6. Non-Functional Requirements

### 6.1 Performance

| ID | Verification | Evidence | Method | Status |
|----|--------------|----------|--------|--------|
| NFR-P-001 | Live-endpoint throughput test over 10-minute window | `tests/performance/results/{ts}/throughput.json` | M-2 | Planned |
| NFR-P-002 | Mock-endpoint latency overhead test | `tests/performance/results/{ts}/overhead.json` | M-2 | Planned |
| NFR-P-003 | Worker count sweep 1→5 | `tests/performance/results/{ts}/worker_scaling.json` | M-2 | Planned |

### 6.2 Reliability

| ID | Verification | Evidence | Method | Status |
|----|--------------|----------|--------|--------|
| NFR-R-001 | Injected-transient-failure batch test | `tests/reliability/results/{ts}/transient.json` | M-2 | Planned |
| NFR-R-002 | SIGKILL-during-batch test | `tests/reliability/results/{ts}/checkpoint.json` | M-2 | Planned |
| NFR-R-003 | Ledger-entry-count reconciliation | `tests/reliability/results/{ts}/ledger_integrity.json` | M-2 | Planned |
| NFR-R-004 | Injected-401 halt test | `tests/reliability/results/{ts}/fail_fast.json` | M-2 | Planned |

### 6.3 Security

| ID | Verification | Evidence | Method | Status |
|----|--------------|----------|--------|--------|
| NFR-S-001 | Key-pattern grep across all output files | CI test output | M-1, M-2 | Implemented |
| NFR-S-002 | `.gitignore` coverage test + audit command | `test_report.py::test_audit_gitignore` | M-1, M-4 | Planned |
| NFR-S-003 | `!!python/object` YAML rejection | `test_config.py::test_unsafe_yaml_rejected` | M-1 | Implemented |
| NFR-S-004 | `pip-audit` in CI | CI job output | M-4 | Planned |
| NFR-S-005 | Install-from-lockfile CI job | CI job output | M-4 | Planned |

### 6.4 Portability

| ID | Verification | Evidence | Method | Status |
|----|--------------|----------|--------|--------|
| NFR-PO-001 | CI matrix on Python 3.12, 3.13, 3.14 | CI output | M-1 | Planned |
| NFR-PO-002 | CI matrix on Linux, macOS, Windows | CI output | M-1 | Planned |
| NFR-PO-003 | Three-deps-only install test | CI job: install with only hard deps | M-4 | Planned |
| NFR-PO-004 | Multi-provider integration tests | `tests/integration/results/{ts}/providers.json` | M-2 | Planned |

### 6.5 Maintainability

| ID | Verification | Evidence | Method | Status |
|----|--------------|----------|--------|--------|
| NFR-M-001 | Import graph inspection | Generated dependency graph | M-3 | Implemented |
| NFR-M-002 | Coverage report | CI coverage artifact | M-1 | Implemented |
| NFR-M-003 | Two-client concurrent test | `test_client.py::test_isolation` | M-1 | Implemented |
| NFR-M-004 | Add-hypothetical-provider walkthrough | Recorded in Ops Guide | M-4 | Planned |
| NFR-M-005 | Changelog + lockfile diff review process | `CHANGELOG.md`, PR review | M-3 | Planned |

### 6.6 Usability

| ID | Verification | Evidence | Method | Status |
|----|--------------|----------|--------|--------|
| NFR-U-001 | Error-path review | Inspection checklist | M-3 | Planned |
| NFR-U-002 | `--help` output test | `test_report.py::test_help_output` | M-1 | Planned |
| NFR-U-003 | SRS-to-docs cross-check | Inspection checklist | M-3 | Planned |

## 7. Coverage Summary

| Category | Total | Implemented | Planned | Not Started |
|----------|-------|-------------|---------|-------------|
| Functional (FR) | 42 | 31 | 11 | 0 |
| Security (SEC) | 6 | 4 | 2 | 0 |
| Interface (IR) | 4 | 4 | 0 | 0 |
| NFR Performance | 3 | 0 | 3 | 0 |
| NFR Reliability | 4 | 0 | 4 | 0 |
| NFR Security | 5 | 2 | 3 | 0 |
| NFR Portability | 4 | 0 | 4 | 0 |
| NFR Maintainability | 5 | 3 | 2 | 0 |
| NFR Usability | 3 | 0 | 3 | 0 |
| **Total** | **76** | **44** | **32** | **0** |

Status definitions:

- **Implemented:** Code and unit test exist and pass. Integration tests may still be pending where marked M-2.
- **Planned:** Requirement documented, implementation not yet written or test not yet run. May be imminent (e.g., credential resolution order scheduled for next CC task) or deferred (e.g., performance tests requiring live endpoint budget).
- **Not Started:** Requirement is documented but work has not yet been scoped. Zero currently.

## 8. Known Gaps Between Current Code and This RTM

The RTM reflects the post-documentation baseline. The following items are documented requirements whose current code is inconsistent and require a cleanup CC task to align:

1. **FR-009a (DotEnvProvider resolution order).** Current `key_manager.py` reads only project-local `.env`. User-level resolution needs adding.
2. **FR-010 (reactive authentication).** Current `key_manager.py` has expiry metadata logic from an earlier design. Needs removal.
3. **FR-036 through FR-041 (setup, add-provider, discover-models, verify).** No CLI subcommands exist yet for these. Implementation required.
4. **FR-040 (endpoint as source of truth for models).** Current `configs/models.yaml` has placeholder model IDs. Needs replacement with verified IDs from the `usai-api-tester` companion tool, and live-discovery logic added.

These gaps are expected for a baseline documentation pass that predates the code. They are the scope for the first post-documentation implementation task.

## 9. Maintenance

This RTM is updated whenever:

- A requirement is added, modified, or removed in the SRS or NFR.
- A module is added, renamed, or removed.
- A test file or test case is added or renamed.
- A requirement's implementation status changes (Planned → Implemented, or gap closure).

Changes to the RTM accompany changes to the underlying artifact in the same commit. The RTM is never updated speculatively or in advance of the change it documents.
