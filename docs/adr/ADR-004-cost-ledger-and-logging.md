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
