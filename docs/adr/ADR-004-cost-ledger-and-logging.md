# ADR-004: Append-Only Cost Ledger with Metadata-Only Default

**Status:** Accepted
**Date:** 2026-04-24

## Context

The harness logs LLM calls to support cost accounting, debugging, and reproducibility. Two related questions need answers: what does the cost ledger record, and what does the call log record?

The ledger feeds cost reports and audit trails. It needs to be durable and tamper-evident. It should not grow to include prompt or response content, because that introduces PII exposure and privacy review burden that varies per workload. Cost rates may be zero during free credit periods, so the ledger should allow retroactive cost computation once billing activates.

The call log has a different purpose. Some debugging genuinely needs full content. Routine operation should not write prompts or responses to disk by default, both for privacy and for disk-use reasons.

## Decision

The cost ledger at `cost_ledger.jsonl` is append-only. Entries are never deleted or truncated. Each entry records:

- Timestamp
- Project and job tags
- Model identifier
- Prompt tokens, completion tokens, total tokens
- Rate applied at the time of the call
- Computed cost

The ledger never records prompt or completion text. Enforcement is via a typed dataclass in `cost.py`, not by convention. A caller cannot accidentally write content into the ledger because the dataclass has no field for it.

The call log captures metadata per call by default: timestamp, model requested, model returned, status, latency, token counts, error category. Full prompt and response logging is enabled via an explicit `log_content=True` flag, documented as debugging-only and potentially PII-exposing.

## Consequences

Cost and usage audit is always possible. PII exposure through the ledger is structurally impossible regardless of workload.

Retroactive cost computation is possible. Rates live in `models.yaml`. Ledger entries record the rate that was applied at the time of the call, so rate changes do not invalidate historical records.

Debug logging remains available when needed but requires intentional opt-in per job. Content logs, when enabled, go to the regular call log, not the cost ledger.

Downstream workload evaluation can cite ledger and call-log artifacts as reproducibility evidence without requiring privacy review of those artifacts, because the defaults contain no user or respondent content.

## Amendment, 2026-04-29 — per-model granularity, retroactive cost computation removed

Two coupled defects in the original implementation surfaced during a multi-rater pool run on 2026-04-29: `LedgerEntry.model` always recorded the project default, regardless of which models actually ran (so a 10-task batch with two models produced one ledger line attributing all tokens to the default's rates), and `complete()`-only workflows produced no ledger entries at all (the flush path was wired only into `batch()`). Both bugs were structural, not bookkeeping mistakes — the data model was single-model and the flush plumbing was batch-only.

The ledger granularity changes from one-entry-per-call to one-entry-per-(model, flush-point) pair. A flush-point is the end of a `batch()` call or the close of the client. `CostTracker` is now keyed by model name internally and resets each model's totals after every flush, so entries describe deltas since the previous flush rather than cumulative totals. `LedgerEntry` gains a `flush_reason` field with the literal values `"batch_end"` or `"client_close"`. A model with zero calls since the last flush does not produce an entry.

Retroactive cost computation (FR-032 in earlier SRS revisions) is removed as a goal. The ledger is an estimation tool, not a billing-reconciliation artifact. Rates baked into each entry reflect the catalog values active at flush time. If rates change later, historical entries do not update; downstream consumers that need exact cost reconciliation should join against an external billing record. FR-032 is deleted from the SRS as part of this change. FR-030 and FR-031 are rewritten to describe per-(model, flush-point) granularity.

The call log is unchanged. It remains per-call. The two subsystems are deliberately at different granularities: the call log answers "what happened on every call" (which is what debugging and per-call cost reconciliation need), and the ledger answers "what did this run cost" (which is what reporting and budget tracking need). The ledger's coarser granularity is a feature.

*Source:* CC task 2026-04-29_per_model_cost_ledger.
