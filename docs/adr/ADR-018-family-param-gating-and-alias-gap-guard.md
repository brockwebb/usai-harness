# ADR-018: Omit family-rejected sampling params + hard-fail un-aliased pool SKUs

**Status:** Accepted (2026-06-16)
**Supersedes (in part):** ADR-012's "params forwarded unchanged" at the request layer — see Decision.

## Context

`claude_4_8_opus` (a downstream project's oracle role) returned HTTP 400 from USAi:
`ValidationException: temperature is deprecated for this model`. Wire-verified root cause — three
compounding faults:

1. `transport.send` put `temperature` in the request payload **unconditionally** (param defaulted
   to `0.0`), so it was sent even to models whose family rejects it (Claude lines).
2. The call paths (`complete()`, batch `_make_request()`) never consulted the family catalog at
   request time, so nothing dropped a rejected param.
3. **The class bug:** the active pool SKUs (the oracle + all three eval-panel members) matched **no
   family-catalog alias**, so per-model parameter validation was *skipped* and params passed to the
   transport **unvalidated**. `_validate_pool_param_overrides` merely `log.warning`-ed and continued.

The symptom (one dead model) was cheap to misread as a model outage; the real exposure is that any
future pool SKU added without a `families.yaml` alias row silently re-enters this unvalidated state.

## Decision

1. **Transport omits `temperature`/`top_p` when `None`.** An explicit value (incl. `0.0`) is still
   sent; `None`-valued extra kwargs are dropped so a gated param never leaks as a null.
2. **The client gates by the family catalog at request time.** `complete()` and `_make_request()`
   pass `None` for a param the model's family rejects (`accepts_temperature`/`accepts_top_p:
   false`). Unknown/unverified ⇒ pass through (never strip what we cannot prove unsupported). This
   refines ADR-012: a per-call value is still forwarded *unchanged when the family accepts it* (no
   range clamping at runtime), but a family that *rejects* the param no longer receives it.
3. **An un-aliased pool SKU is a hard config-load failure** (`ConfigValidationError`), not a warn-
   and-pass-through. The error names the SKU/provider and tells the operator to add the
   `provider_aliases` row (preserving the major version). The check runs *after* structural
   validation (pool validity, default_model, provider consistency) so those errors surface first.
4. Aliased the four active-pool SKUs that had no row: `claude_4_8_opus`→`claude-opus-4`,
   `claude_4_6_sonnet`→`claude-sonnet-4`, `gpt-5.5-latest-guardrails-defaultv2`→`gpt-5`,
   `grok-4-latest-guardrails-defaultv2`→`grok-4`.

## Consequences

- Opus 4.8 (and any temperature-rejecting Claude line) is callable through the normal path; verified
  end-to-end (HTTP 200, `temperature` absent on the wire).
- Temperature-accepting families (gemini/gpt/grok/llama) are **unaffected** — they still carry
  temperature (regression-guarded).
- **A new pool SKU without an alias row now fails loudly at config load.** This is intentional: an
  un-aliased SKU means parameters go to the provider unvalidated, which is exactly how the 400 above
  happened. Do **not** relax this back to a warning — add the alias row instead. There is no
  legitimate reason to run a pool member that resolves to no family.

## Notes

Class-fix is Option A (load-time assertion) from the originating task. A stricter runtime default
(refuse unmatched SKUs at call time, Option B) was deliberately NOT adopted: it would change request
behavior for every consumer and warrants a consumer survey first. The load-time failure is the
earlier, cheaper, lower-blast-radius signal.
