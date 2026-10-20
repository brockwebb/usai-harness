# Docs and spec alignment

## Why this matters

The project is explicitly audit-oriented, so stale prose is a functional risk.

## Current drift

| Area | Current issue | Suggested resolution |
| --- | --- | --- |
| Project config examples | Some docs still show `project`, `ledger_path`, and `log_dir` in `usai_harness.yaml`. | Remove those fields from examples and point to `usai-harness schema project-config`. |
| Parameter validation | Some docs say per-task temperature validates against catalog ranges. | Say project config overrides validate through the family catalog when known, and provider responses remain authoritative. |
| Progress default | SRS says `progress=None` is the old silent default. | Update to say default is `text_progress`; `progress=None` opts out. |
| Checkpoint language | API docs describe a `checkpoint_path` argument that current `batch()` does not expose. | Reword around current auth recovery and `ProgressEvent.result` checkpoint recipe. |
| LiteLLM wording | User docs can imply the LiteLLM backend is ready. | State that it is optional and planned until implemented. |
| Security support version | `SECURITY.md` says latest 0.1.x while package is 0.9.0. | Update supported versions before any broader release. |

## Suggested doc patch shape

1. Start with README and ops guide because users read those first.
2. Update API reference next because it sets caller expectations.
3. Update SRS and RTM last so requirements match current behavior.
4. Run `usai-harness validate-config` against every YAML example that is meant to be copyable.

## Acceptance checklist

- No copyable config example contains schema-rejected top-level fields.
- Every CLI listed in README appears in API reference.
- Every implemented CLI appears in SRS or a clearly marked future ADR.
- RTM counts match SRS requirement IDs.
- LiteLLM status is consistent across README, API reference, SRS, and RTM.
