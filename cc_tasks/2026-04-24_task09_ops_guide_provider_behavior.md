# CC Task 09: Ops guide additions for provider-specific behavior

**Date:** 2026-04-24
**File:** `cc_tasks/2026-04-24_task09_ops_guide_provider_behavior.md`
**Predecessor:** Task 08 (Gemini smoke test)
**Estimated effort:** ~30 min

## Problem

The Gemini smoke test (Task 08) surfaced four behavioral divergences between USAi and Gemini that are undocumented. Users following the README's "model-agnostic" framing will hit them and not understand what's happening.

## Fix

Add a "Provider-specific behavior" section to the operations guide documenting the four findings. Add a brief caveat to the README's model-agnostic claim pointing readers to that section.

## Files to change

1. **Ops guide** (find via `ls docs/` — handoff mentions one exists; likely `docs/ops_guide.md`, `docs/operations.md`, or similar)
   - Add a new top-level section titled "Provider-specific behavior" near the end, before troubleshooting
   - Four sub-sections (one per finding), each two to four sentences. No two-sentence paragraphs; either one sentence or three or more.

2. **README.md**
   - Wherever the model-agnostic claim is made, add a single-sentence caveat: refer reader to the Provider-specific behavior section of the ops guide for known divergences across endpoints.

## Content for the ops guide section

Use the headings and content below verbatim, adjusting only to match house style. Banned word: "clever". No em-dashes. Italics not bold for emphasis.

### Section: Provider-specific behavior

Lead-in (one paragraph): The harness targets any OpenAI-compatible endpoint, but real endpoints diverge in how they signal failures and what they accept as inputs. The behaviors below have been observed against current endpoints and are stable enough to plan around. They are not bugs in the harness.

#### Authentication failure status codes

USAi returns HTTP 401 or 403 for an invalid API key. The harness catches both and raises `AuthHaltError`, which drains the worker pool cleanly. Gemini's OpenAI-compat endpoint returns HTTP 400 for an invalid key, with a structured JSON body containing `error.status: "INVALID_ARGUMENT"` and a message saying the key is invalid. The harness treats 400 as a non-retryable per-call failure, not as an auth halt. This means a mis-typed Gemini key produces N individual non-retryable failures (one per worker), not a clean halt.

Operational mitigation: run `usai-harness verify` or a single `ping` before any long-running Gemini batch. The first response will reveal an invalid key immediately. Do not rely on the pool halting partway through.

The harness deliberately does not attempt to detect auth-failure 400s by inspecting body content. Pattern matching on error message text would be fragile against provider rephrasings and prone to false positives on legitimate per-call 400s (malformed bodies, unsupported parameters, context-length exceeded — all of which Gemini also returns as 400).

#### Gemini 2.5 thinking tokens and `max_tokens`

Gemini 2.5 models reserve a portion of the response budget for internal thinking tokens before producing visible content. Setting `max_tokens` below approximately 64 on Gemini 2.5 models can cause the response content to be empty even when the call succeeds with HTTP 200. Recommended floor for Gemini 2.5 smoke tests is `max_tokens=64`. For production batches, size based on the actual content length expected plus a thinking-overhead margin.

This behavior is specific to Gemini 2.5. Earlier Gemini models and other providers do not reserve thinking tokens this way.

#### Provider model ID naming

Gemini's `/models` endpoint returns IDs in the form `models/gemini-2.5-flash` rather than the bare `gemini-2.5-flash`. The harness round-trips these correctly: `discover-models` caches them as Gemini returns them, and the live catalog merge uses the full form. Pass model IDs verbatim from the live catalog rather than typing the short form. The `model_requested` and `model_returned` log fields will both reflect the full form for Gemini calls.

#### Provider registration is interactive

`usai-harness add-provider` prompts for credentials and endpoint details interactively. There is currently no flag-based path for scripted bring-up. For now, register providers manually on each machine that needs them. Once registered, `discover-models <name>` and the rest of the CLI surface work non-interactively.

## README.md addition

Locate the section that claims model-agnosticism (likely the introduction or feature list). Add a single sentence at the end of that section:

> Endpoint behavior diverges in practice; see `docs/<ops-guide-filename>` section "Provider-specific behavior" for known differences in auth-failure handling, model ID naming, and per-provider parameter quirks.

## Verification checklist

- [ ] New ops guide section has four sub-sections matching the headings above
- [ ] No two-sentence paragraphs anywhere in the new content
- [ ] No em-dashes; banned word "clever" not present
- [ ] README caveat added with correct path to the ops guide
- [ ] `seldon verify` passes
- [ ] Markdown renders correctly

## Out of scope

- Code changes (handled in Task 10)
- Adding per-provider behavior tables (premature; four findings is too few for a table)
- Documenting USAi-specific behavior beyond the auth comparison (separate task if needed)
- Updating SRS or ADRs (these are operational notes, not requirements changes)

## Graph

Register as `ResearchTask` with state `proposed`. Transition to `completed` on merge.
