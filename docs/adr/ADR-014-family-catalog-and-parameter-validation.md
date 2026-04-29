# ADR-014: Family Catalog and Parameter Validation

**Status:** Accepted
**Date:** 2026-04-29

## Context

ADR-012 originally specified per-model parameter validation at config-load time, sourced from the catalog entries the harness writes via `discover-models`. Those entries were inferred from each provider's API behavior with no source-of-record beyond what the live `/models` endpoint returned. The 0.3.0 strip-validation amendment to ADR-012 removed that validation because it was a second source of truth that drifted: GPT-5 and Claude reject `temperature` entirely, Gemini Flash accepts it in `[0, 1]`, other Gemini variants accept `[0, 2]`, and the catalog could not capture this without becoming a per-model decision table that goes stale on every provider release.

The 0.3.0 strip was correct for the catalog. It is the wrong outcome for the user. Without any validation, an out-of-range temperature in `usai_harness.yaml` fails at API call time with a vendor-specific error message, often after a long-running batch has already started. That is poor UX for the common case. The right behavior is: catch obvious mismatches (Claude 4.x rejecting `temperature`, Gemini's range cap) at config load, before the first call, with a citable explanation.

The data the harness needs to do that exists. Anthropic publishes parameter docs. Cloud providers publish more. Community trackers fill in gaps. The information just hasn't been sitting in a structured place inside the harness.

## Decision

Ship a curated *family catalog* with the package at `usai_harness/data/families.yaml`, and use it to validate per-model parameters at config-load time.

### Granularity: family, not SKU

The catalog is keyed on **vendor + product line + major version**. Major versions are where parameter acceptance actually changes. Claude 4.x rejects `temperature`; a hypothetical Claude 5.x could reintroduce it, and that would be a new family entry. Within a major version, dated SKUs (`claude-sonnet-4-5-20241022`, `claude-sonnet-4-6-20250901`, ...) share parameter behavior. Adding a new dated SKU under an existing major line is a one-row alias addition, not a new family entry.

Family keys: `claude-sonnet-4`, `claude-opus-4`, `claude-haiku-4`, `gemini-2.5`, `gemini-2.0`, `gpt-5`, `o-reasoning`, `llama-4`, `grok-4`. Aliases preserve the major version (`claude_4_5_sonnet` → `claude-sonnet-4`, never `claude-sonnet`). The `o-reasoning` family is an intentional exception that covers o1, o3, and successors together because they all reject sampling parameters; if a future o-series variant changes that, it gets split into `o3-reasoning` etc.

### Citation tiers

Every parameter field carries a tier label so users know how strong the source is:

- `t1` — vendor primary doc (model card, official API reference)
- `t2` — cloud provider doc (AWS Bedrock, Azure OpenAI, Vertex)
- `t3` — third-party aggregator or community guide
- `t4` — empirical (verified against the live endpoint by harness maintainers)

Fields whose source is uncertain are marked `value: needs_verification`. The validator warns rather than rejects on those — the harness will not silently allow a value the catalog isn't sure about, but it also will not block a config on data the maintainers haven't confirmed.

### Validation behavior

`ConfigLoader` instantiates a `FamilyCatalog` at construction. For every catalog entry, it resolves `(provider, name)` through the alias table and attaches `family_key` and `family_entry` to the resulting `ModelConfig`. The runtime catalog (the `discover-models` output) still answers "what models exist." The family catalog answers "what parameters do those models accept." Two different catalogs, one consumer.

At `load_project_config()`:

1. **Pool resolution pass.** Each pool member is matched against the merged catalog (existing behavior). If the model has a family entry, validation runs in step 2. If not, the loader logs a clear warning naming `(provider, name)` and notes that parameter validation is skipped for that member. Unknown aliases pass through; catalog drift cannot block valid configs.

2. **Parameter validation pass.** For each pool member with a family entry, the loader walks recognized parameter overrides (`temperature`, `top_p`, `top_k`, `frequency_penalty`, `presence_penalty`, `max_tokens`):
   - `accepts_X.value == false` → `ConfigValidationError` citing the model, the parameter, the family key, and the source recorded in the catalog.
   - `accepts_X.value == true` and a `range` is present → validate the value falls inside the range; raise on miss with the range cited.
   - `accepts_X.value == "needs_verification"` → log a warning naming the parameter and pass through.
   - `range == "needs_verification"` (the value is accepted but the range is unconfirmed) → warn and pass through.

The same pattern applies to project-level defaults (`temperature`, `max_tokens`) — those are validated against the `default_model`'s family entry.

### Relationship to existing ADRs

- **ADR-012 (project config schema).** ADR-012's original validation rules were scoped to *catalog model entries*, which `discover-models` writes from API behavior with no source. The 0.3.0 amendment removed that. ADR-014 reintroduces validation but sources it from a separately-curated artifact with citation tiers. Different mechanism, same surface behavior for the common case (an obvious parameter mismatch fails at config load with a clear message), but the new mechanism has provenance and survives a vendor's rate-limit or response-format change.

- **ADR-009 (catalog from endpoint as source of truth).** ADR-009's catalog (live endpoint introspection) and ADR-014's catalog (curated families) answer different questions. The runtime catalog is updated by `usai-harness discover-models`. The family catalog is updated by a PR to the harness repo when a new major model line ships. Both are version-controlled in their own way.

- **ADR-013 (project bootstrap).** No interaction. `project-init` writes a config; `ConfigLoader` validates it. Family validation runs whenever any project config is loaded, which includes the config `project-init` just wrote.

### Surface

A new CLI subcommand prints the catalog: `usai-harness families [--family KEY] [--format {table,yaml,markdown}]`. The default lists every family with vendor and brief description. `--family` shows a full entry with citation tiers. `--format markdown` produces a research-methodology-friendly table that can be pasted into a paper's appendix.

The `families` command complements `list-models` (which prints provider-specific identifiers from the merged runtime catalog). Together they answer "what models can I use" and "what does the harness know about their parameter behavior."

### What this does not do

This task does not introduce empirical verification per endpoint. A future `usai-harness verify-model` command could record empirical evidence and upgrade tier-3 entries to tier-4 for a specific endpoint. That is a follow-up, not part of 0.4.0.

This task does not block configs on `needs_verification` fields. Those warn. Blocking would force the catalog to be exhaustive at the moment a user lands on a new model — too brittle for the common path.

## Consequences

A user who configures `claude_4_5_sonnet` with `temperature: 0.5` gets a clear error at config load: "family `claude-sonnet-4` does not accept temperature on this model. Source: AWS Bedrock Claude 4.5 Sonnet parameter docs note temperature/top_p mutual exclusion." That is exactly the diagnostic 0.3.0 sacrificed and 0.4.0 restores.

Researchers writing methodology sections can run `usai-harness families --format markdown` to dump a citable parameter-behavior table for the families their study touched. Citation tiers in the rendered table tell reviewers how strong each claim is.

The catalog is updated by PR. When a new major model line launches, a maintainer adds an entry, fills in citation-tier-labeled values, lists known aliases, and ships a release. The federal-survey-concept-mapper and similar consumers do not need to rebuild anything; they just `pip install --upgrade` and re-run `project-init` to pick up the new validation rules.

The 0.3.0 decision stands for the runtime catalog. The harness still does not synthesize parameter rules from API behavior. The family catalog is the only place validation rules come from, and that file is hand-curated with sources.

The catalog has known gaps. Several fields are `needs_verification`. Those warn rather than block, and the warning text names the field and the family. As gaps close (empirical verification, vendor docs improvement, community correction), the tier labels upgrade and the warnings disappear. The catalog gets better over time without code changes elsewhere.
