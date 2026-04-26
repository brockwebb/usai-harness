# Requirements Traceability Matrix — usai-harness

**Version:** 1.1
**Date:** 2026-04-25
**Status:** Audited (Tasks 06-10 reflected; baseline gaps closed)

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
| FR-009 | `key_manager.py::AzureKeyVaultProvider`, `pyproject.toml` extras | `test_key_manager.py::test_azure_*` | M-1 | ADR-003, ADR-005 | Implemented |
| FR-009a | `key_manager.py::DotEnvProvider` resolution logic | `test_key_manager.py::test_dotenv_resolution_order_is_exact` | M-1 | ADR-008 | Implemented |

### 3.3 Authentication Handling

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-010 | `key_manager.py` (absence of expiry state) | `test_key_manager.py::test_no_meta_file_created` | M-1, M-3 | ADR-002 | Implemented |
| FR-011 | `worker_pool.py::AuthHaltError`, `client.py` error path | `test_worker_pool.py::test_401_halts_pool_and_preserves_results`, `test_worker_pool.py::test_403_halts_pool` | M-1, M-2 | ADR-002 | Implemented |
| FR-012 | `setup_commands.py::handle_ping`, `cli.py` | `test_setup_commands.py::test_ping_*`, `test_cli.py::test_ping_invokes_handler` | M-1 | ADR-002 | Implemented |

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
| FR-027 | `logger.py` default entry schema, `client.py::_record_outcome`/`_record_result` | `test_logger.py::test_log_call_writes_entry`, `test_logger.py::test_log_entry_includes_error_body_when_present`, `test_logger.py::test_log_entry_omits_error_body_when_none` | M-1, M-3 | ADR-004, ADR-007 (post-amendment) | Implemented |
| FR-028 | `client.py` `log_content` flag, `logger.py` opt-in fields | `test_client.py::test_content_logging_off_by_default`, `test_client.py::test_content_logging_opt_in_writes_content`, `test_client.py::test_content_logging_warning_on_stderr` | M-1 | ADR-004, ADR-007 | Implemented |
| FR-029 | `client.py`, `logger.py`, `report.py` | `test_client.py::test_model_echo_matching`, `test_client.py::test_model_echo_mismatch_logged`, `test_report.py::test_report_detects_mismatch` | M-1, M-2 | ADR-007 | Implemented |

### 3.9 Cost Tracking

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-030 | `cost.py::CostTracker` | `test_cost.py::test_append_only` | M-1 | ADR-004 | Implemented |
| FR-031 | `cost.py::LedgerEntry` dataclass | `test_cost.py::test_ledger_entry_has_no_content_fields` | M-1, M-3 | ADR-004, ADR-007 | Implemented |
| FR-032 | `cost.py` rate recording | `test_cost.py::test_retroactive_compute` | M-1 | ADR-004 | Implemented |

### 3.10 Reporting

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-033 | `report.py::build_summary` | `test_report.py::test_summary_*` | M-1 | Component contract | Implemented |
| FR-034 | `report.py::cost_report_cmd` | `test_report.py::test_cost_report_cli` | M-1 | Component contract | Implemented |
| FR-035 | `audit_command.py::handle_audit`, `cli.py` | `test_audit.py::*`, `test_cli.py::test_audit_*` | M-1, M-4 | ADR-007 | Implemented |

### 3.11 Setup and Model Discovery

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| FR-036 | `setup_commands.py::handle_init`, `cli.py` | `test_setup_commands.py::test_init_*`, `test_cli.py::test_init_invokes_handler` | M-1 | ADR-009 | Implemented |
| FR-037 | `setup_commands.py::handle_add_provider`, `cli.py` | `test_setup_commands.py::test_add_provider_*`, `test_cli.py::test_add_provider_passes_name` | M-1 | ADR-009 | Implemented |
| FR-038 | `setup_commands.py::handle_discover_models`, `cli.py` | `test_setup_commands.py::test_discover_models_*`, `test_cli.py::test_discover_models_*` | M-1 | ADR-009 | Implemented |
| FR-039 | `setup_commands.py::handle_verify`, `cli.py` | `test_setup_commands.py::test_verify_*`, `test_cli.py::test_verify_invokes_handler` | M-1 | ADR-009 | Implemented |
| FR-040 | `config.py::_apply_live_catalog` | `test_config.py::test_live_catalog_*`, `test_config.py::test_live_model_not_in_repo_gets_synthesized_defaults`, `test_config.py::test_repo_model_not_in_live_is_dropped` | M-1 | ADR-009 | Implemented |
| FR-041 | `setup_commands.py` getpass usage | `test_setup_commands.py::test_no_input_used_for_keys` | M-1, M-3 | ADR-009 | Implemented |
| FR-042 | `config.py::_apply_live_catalog` drop warning | `test_config.py::test_apply_live_catalog_warns_on_dropped_models` | M-1 | ADR-009 amendment | Implemented |

## 4. Security Requirements

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| SEC-001 | `redaction.py::redact_secrets`, `logger.py`, `transport.py` error body capture, `client.py` exception path | `test_redaction.py::*`, `test_transport.py::test_error_body_is_redacted`, `test_transport.py::test_error_body_snippet_redacted`, `test_client.py::test_complete_exception_is_redacted` | M-1 | ADR-007 (post-amendment) | Implemented |
| SEC-002 | `config.py`, `setup_commands.py` use `yaml.safe_load`/`safe_dump` | inspection of imports; no `yaml.load` calls | M-3 | ADR-007 | Implemented |
| SEC-003 | `transport.py::HttpxTransport` TLS default, warning on verify=False | `test_transport.py::test_tls_verify_disabled_warns_per_call`, `test_transport.py::test_tls_verify_default_silent` | M-1 | ADR-007 | Implemented |
| SEC-004 | `configs/models.yaml` schema (no secret fields) | `test_config.py::test_providers_block_parsed`, inspection | M-3 | ADR-003 | Implemented |
| SEC-005 | `.gitignore`, `audit_command.py::handle_audit` | `test_audit.py::test_gitignore_*` | M-1, M-3, M-4 | ADR-007 | Implemented |
| SEC-006 | `requirements.lock` at repo root, `tests/test_repo_hygiene.py` | `test_repo_hygiene.py::test_requirements_lock_*` | M-1, M-4 | ADR-005, ADR-007 | Implemented |

## 5. Interface Requirements

| ID | Implementation | Test | Method | Source | Status |
|----|----------------|------|--------|--------|--------|
| IR-001 | `usai_harness/__init__.py` exports | inspection (USAiClient surface stable) | M-1, M-3 | SRS Section 6 | Implemented |
| IR-002 | `pyproject.toml` console script `usai-harness = "usai_harness.cli:cli_main"` | `test_cli.py::*` (all dispatcher tests) | M-1 | SRS Section 6 | Implemented |
| IR-003 | `configs/models.yaml` schema, `config.py` validation | `test_config.py::test_providers_block_parsed`, `test_config.py::test_provider_with_api_key_secret_loads`, `test_config.py::test_provider_with_neither_field_raises`, `test_config.py::test_secret_map_*` | M-1, M-3 | SRS Section 6 | Implemented |
| IR-004 | `config.py::load_project_config` validation | `test_config.py::test_project_config_credentials_*`, `test_config.py::test_load_project_config_valid` | M-1 | SRS Section 6 | Implemented |
| IR-005 | `config.py` `error_body_snippet_max_chars` validation, `transport.py` consumer | `test_config.py::test_error_body_snippet_max_chars_*`, `test_transport.py::test_error_body_snippet_*` | M-1 | ADR-007 (post-amendment) | Implemented |

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
| NFR-S-002 | `.gitignore` coverage test + audit command | `test_audit.py::test_gitignore_all_present_passes`, `test_audit.py::test_gitignore_missing_reports`, `test_audit.py::test_gitignore_missing_fix_appends` | M-1, M-4 | Implemented |
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
| Functional (FR) | 43 | 42 | 1 | 0 |
| Security (SEC) | 6 | 6 | 0 | 0 |
| Interface (IR) | 5 | 5 | 0 | 0 |
| NFR Performance | 3 | 0 | 3 | 0 |
| NFR Reliability | 4 | 0 | 4 | 0 |
| NFR Security | 5 | 3 | 2 | 0 |
| NFR Portability | 4 | 0 | 4 | 0 |
| NFR Maintainability | 5 | 3 | 2 | 0 |
| NFR Usability | 3 | 0 | 3 | 0 |
| **Total** | **78** | **59** | **19** | **0** |

Status definitions:

- **Implemented:** Code and unit test exist and pass. Integration tests may still be pending where marked M-2.
- **Planned:** Requirement documented, implementation not yet written or test not yet run. May be imminent (e.g., credential resolution order scheduled for next CC task) or deferred (e.g., performance tests requiring live endpoint budget).
- **Not Started:** Requirement is documented but work has not yet been scoped. Zero currently.

## 8. Known Gaps Between Current Code and This RTM

The four baseline gaps documented at v1.0 (FR-009a resolution order, FR-010 reactive auth, FR-036–FR-041 setup CLIs, FR-040 endpoint-authoritative models) were closed in the alignment sweep landed across CC Tasks 01 through 05 (commits `77d1184` through `8ed31c6`).

What remains as Planned at the time of this audit is work gated on either a live USAi endpoint key or CI infrastructure that has not yet been set up. None of these blocks any user-facing functionality.

1. **FR-014 (LiteLLMTransport).** The transport stub exists and raises `NotImplementedError`. Full implementation is intentionally deferred per ADR-001 until the LiteLLM optional path is exercised against a real provider need.
2. **NFR Performance row (P-001 through P-003).** Throughput and overhead measurements require a live endpoint with a key budget and a stable test window.
3. **NFR Reliability row (R-001 through R-004).** Injected-failure scenarios require live-endpoint orchestration; the unit tests cover the harness behavior but not the end-to-end recovery story.
4. **NFR Security S-004 (pip-audit in CI) and S-005 (lockfile install in CI).** No `.github/workflows/` directory exists yet; both depend on a CI workflow being added.
5. **NFR Portability row (PO-001 through PO-004).** Multi-version, multi-OS, and multi-provider verification all need CI matrix runs that have not yet been wired up.
6. **NFR Maintainability M-004 (add-provider walkthrough) and M-005 (CHANGELOG discipline).** M-004 is documentation-only; M-005 depends on `CHANGELOG.md` being kept current PR-by-PR going forward.
7. **NFR Usability row (U-001 through U-003).** Error-path and `--help` reviews are pending; the `--help` substance is verified indirectly by the CLI dispatcher tests in `test_cli.py`.

## 9. Maintenance

This RTM is updated whenever:

- A requirement is added, modified, or removed in the SRS or NFR.
- A module is added, renamed, or removed.
- A test file or test case is added or renamed.
- A requirement's implementation status changes (Planned → Implemented, or gap closure).

Changes to the RTM accompany changes to the underlying artifact in the same commit. The RTM is never updated speculatively or in advance of the change it documents.
