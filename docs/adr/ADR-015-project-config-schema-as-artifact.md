# ADR-015: Project Config Schema as Authoritative Artifact

**Status:** Accepted
**Date:** 2026-04-29

## Context

Until 0.6.0, the project-config schema lived in two places: the `_KNOWN_PROJECT_FIELDS` frozenset in `usai_harness/config.py` and the procedural type checks scattered through `load_project_config()`. Neither was machine-readable. Downstream consumers who needed to document what fields go in `usai_harness.yaml` had no artifact to reference; they ended up copying field lists into their own READMEs and going stale on the next harness release.

Three coupled problems surfaced during the federal-survey-concept-mapper v2 work on 2026-04-29:

1. **No artifact.** The schema lived only in Python. Other tooling could not consume it; IDE YAML extensions could not autocomplete; downstream READMEs duplicated the field list as prose.
2. **Bootstrap template emitting invalid YAML.** `usai_harness/templates/usai_harness.yaml.template` emitted three fields the loader did not recognize (`project`, `ledger_path`, `log_dir`). Every project bootstrapped with `project-init` produced unknown-field warnings on first load. Downstream docs had to teach users to ignore those warnings — a clear sign that something upstream was wrong.
3. **No schema-only validation surface.** Users only learned their YAML was wrong by running an actual workload and watching `load_project_config()` complain. There was no way to validate a config in isolation, separate from credential resolution and catalog lookup.

The leak was structural. Solving it requires a schema artifact, code that consumes the artifact, a CLI that surfaces it, and a template that conforms to it.

## Decision

Ship a JSON Schema artifact at `usai_harness/data/project_config.schema.json`. Make it the single source of truth for the project-config field surface, the contract enforced at config load, and the artifact CLI commands surface to users and to other tooling. Fix the bootstrap template so the YAML it writes validates clean.

### Layer 1: the schema

`usai_harness/data/project_config.schema.json` is JSON Schema draft 2020-12. `$id` is `https://schemas.anthropic.invalid/usai-harness/project-config-v1.json`, a stable harness-namespaced URI. The URL is not required to resolve; it functions as an opaque identifier that IDE tooling can cache. The `$id` only changes on breaking schema changes, allowing a schema bump to be a deliberate, separately-tracked event.

`additionalProperties: false` at the top level. This is the contract that turns unknown fields into hard errors instead of warnings.

`oneOf` enforces mutual exclusion between the legacy `model:` and the pool form `models:`, matching the existing loader behavior.

The schema does NOT encode catalog membership, family-catalog parameter ranges, or credentials backend kwargs. Those are data-dependent: catalog membership comes from the live catalog at runtime, parameter ranges come from the family catalog (ADR-014), and backend kwargs are backend-specific and forwarded verbatim. Schema is structural; data validation is the loader's job.

### Layer 2: code consumes the artifact

`usai_harness/config.py` adds:

- `load_project_config_schema()` — reads the JSON file and returns it as a dict.
- `_KNOWN_PROJECT_FIELDS` is derived from the schema's `properties` keys at module load time. The hand-maintained frozenset is gone.
- The unknown-field warning becomes a `ConfigValidationError` raise. The message names the offending fields, the schema `$id`, and the valid field list, and directs the user to `usai-harness validate-config` for a fuller diagnostic.

This is a breaking change for any consumer that has unknown fields in their `usai_harness.yaml`. The migration is one of: remove the unrecognized field, rename it to a recognized one, or surface a request for a new schema field. All three are visible in the CLI diagnostic.

The procedural type checks in `load_project_config()` are unchanged. They run after schema-conformant parsing and do data-dependent things the schema cannot — catalog lookup, family-catalog parameter validation, cross-provider rejection, default_model resolution. Schema validation and load validation are separable layers; both run, in that order.

### Layer 3: CLI surface

Two new subcommands:

- `usai-harness schema project-config [--format {json,yaml,markdown}]` — prints the schema. JSON is the canonical artifact, YAML is a convenience, Markdown is a human-readable table for docs.
- `usai-harness validate-config <path>` — validates a YAML file against the schema. Exits 0 with `OK: <path> validates against project_config_v1.` on success; exits 1 with one error per line on failure. Does NOT consult the live catalog, resolve model names, or touch credentials. Lazy-imports `jsonschema`; if the optional `[validation]` extras group is not installed, prints a pip-install hint and exits non-zero.

`jsonschema` is added to a `[validation]` optional-dependencies group, not to the hard dependency list. The harness's three hard deps (`httpx`, `python-dotenv`, `pyyaml`) stay three.

### Layer 4: bootstrap template

The template loses the three invalid fields (`project`, `ledger_path`, `log_dir`) and gains a top-of-file comment block pointing readers at the schema artifact, the IDE-tooling directive, and the `validate-config` command. The project name moves into the comment header (it was always documentation, not config). The harness manages `cost_ledger.jsonl` and `logs/` directly; project-config does not configure their paths.

A regression test in `tests/test_project_init.py` round-trips the bootstrap output through `validate-config` so the template cannot drift back to emitting unknown fields.

### Relationship to existing ADRs

- **ADR-011 (project config file convention).** ADR-011 established that project config lives at `usai_harness.yaml` in the project root. ADR-015 makes the schema for that file a first-class artifact and tightens the load contract from warn-and-ignore to schema-strict.
- **ADR-013 (project bootstrap TEVV).** ADR-013 introduced `project-init`. ADR-015 fixes a latent bug in the template ADR-013 shipped, and adds the round-trip regression test.
- **ADR-012 (model pool schema).** Pool semantics are unchanged. The schema encodes the pool's structural shape (array of names or objects); pool-member identity validation against the catalog stays in the loader.
- **ADR-014 (family catalog).** Parameter validation against family rules is data-dependent and stays in the loader. The schema does not duplicate it.
- **ADR-009 (catalog from endpoint as source of truth).** Catalog content is run-time and authoritative for identity. The schema is build-time and authoritative for structure. They answer different questions.

## Consequences

Downstream READMEs stop documenting field-level rules. Instead they reference `usai-harness schema project-config` (for a snapshot) and `usai-harness validate-config <path>` (for the check). The federal-survey-concept-mapper v2 README's bootstrap procedure collapses to:

```bash
usai-harness discover-models
usai-harness project-init --models gemini-2.5-flash,claude_4_5_sonnet --default gemini-2.5-flash
usai-harness validate-config usai_harness.yaml
python src/core/t3_smoke_test.py
```

Each step is a single command surfacing a single failure category. No prose explanation of what fields are valid, no warnings to teach users to ignore.

IDE tooling can autocomplete `usai_harness.yaml` once the schema `$id` resolves to a fetchable URL (publish via GitHub Pages or release asset; tracked as a parking-lot item). Users get red squigglies on unknown fields before they hit `load_project_config()`.

The breaking-change risk is bounded. Any consumer with a stray field gets a clear error and a remediation path. The 0.5.0 catalog-merge reconciliation already broke silent fallbacks; bundling the unknown-field strict rejection into the same release-boundary window keeps the breakage visible in one upgrade rather than two.

The schema is versioned through `$id`. v1 ships in 0.6.0. Future bumps are deliberate, ADR-tracked events. Tooling that caches by `$id` is robust across patch and minor releases that do not change the schema; it sees the bump explicitly when the URI changes.

What this does not do: encode catalog membership, family-catalog parameter ranges, or credentials kwargs. Those remain in code or in the family-catalog YAML because they are data, not structure. A future ADR could ship a separate `runtime_catalog.schema.json` for the user-level live catalog if that surface starts to leak; ADR-015 deliberately scopes itself to project config to keep the change reviewable.
