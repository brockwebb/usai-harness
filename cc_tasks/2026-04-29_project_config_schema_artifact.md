# CC Task: Project-config schema as authoritative artifact + bootstrap template fix

**Date:** 2026-04-29
**Repo:** `/Users/brock/Documents/GitHub/usai-harness`
**Targets release:** 0.6.0 (follows 0.5.0 catalog merge reconciliation)
**Priority:** Eliminates schema-leak between the harness and downstream consumers; fixes a bug in the bootstrap template that emits schema-invalid YAML.

---

## Goal

Make the harness the single authoritative source for the project-config schema, and fix the `project-init` template so the YAML it writes is schema-valid out of the box. Three layers:

1. **Schema artifact.** A machine-readable JSON Schema for project-config ships with the package as `usai_harness/data/project_config.schema.json`. This is the source of truth for what fields are valid, what types they accept, and what their defaults are. The existing `_KNOWN_PROJECT_FIELDS` frozenset and the procedural validation in `load_project_config()` become consumers of the schema, not the source.

2. **CLI access.** Two new subcommands: `usai-harness schema project-config` prints the schema (default JSON, optional `--format yaml|markdown`). `usai-harness validate-config <path>` validates a YAML file against the schema and prints the same diagnostics `load_project_config()` would emit, but without requiring the user-level catalog or any model resolution to be set up. Both subcommands work in any environment that has the harness installed; downstream consumers stop needing to copy schema knowledge into their own docs.

3. **Bootstrap template fix.** `usai_harness/templates/usai_harness.yaml.template` currently emits three fields that the schema rejects (`project`, `ledger_path`, `log_dir`). Every project bootstrapped with `project-init` produces unknown-field warnings on first load. Remove the three invalid fields. Move the project-name comment to a top-of-file YAML comment (it is documentation, not config). Document that ledger and log paths are harness-managed, not project-config.

---

## Background — why this matters

The federal-survey-concept-mapper v2 README contained schema knowledge — a list of valid fields, an explanation of what to drop and why. That was a symptom of three coupled problems:

1. The harness has no machine-readable schema artifact. The schema lives only in `_KNOWN_PROJECT_FIELDS` (a Python frozenset) plus the procedural type checks scattered through `load_project_config()`. Downstream consumers cannot reference the schema without reading Python code.
2. The `project-init` template emits invalid fields that downstream docs then have to warn users about ("the harness will warn about these; ignore the warnings").
3. There is no "validate this YAML" command. Users only learn their YAML is wrong by running an actual workload, which is the wrong layer for schema diagnostics.

Fixing all three eliminates the leak. Downstream READMEs can then say "the harness validates this; run `usai-harness validate-config v2/usai_harness.yaml`" and stop trying to document field-level rules they don't own.

---

## What "done" looks like

### Layer 1: Schema artifact

Create `usai_harness/data/project_config.schema.json`. JSON Schema draft 2020-12. Fields covered: `model`, `models`, `default_model`, `provider`, `temperature`, `max_tokens`, `system_prompt`, `workers`, `batch_size`, `credentials`. Constraints encode what `load_project_config()` actually checks today:

- `models`: array of `string | {name: string, ...}` items, minimum length 1; the per-member object form allows additional properties so per-model overrides like `temperature` flow through (validation against the family catalog stays in code, since it is data-dependent — the schema cannot encode "this temperature is in range for this family").
- `model` and `models` are mutually exclusive (use `oneOf`).
- `provider`: string. The schema does not enumerate provider names (those come from the live catalog at load time, not from the schema).
- `temperature`: number. No range here either — same reason as `provider`.
- `max_tokens`: integer >= 1.
- `workers`: integer 1..10 (the existing `MAX_WORKERS` constant).
- `batch_size`: integer >= 1.
- `credentials`: object with `backend` enum of `["dotenv", "env_var", "azure_keyvault"]`, additional properties allowed for backend-specific kwargs.
- `additionalProperties: false` at the top level — this is the contract that makes unknown fields hard errors instead of warnings.

Add a `$id` like `https://schemas.anthropic.invalid/usai-harness/project-config-v1.json` (a stable, harness-namespaced URI; the URL does not have to resolve, but it has to be stable across releases so IDE tooling can cache it). Bump `$id` only on breaking schema changes.

Update `pyproject.toml` `[tool.setuptools.package-data]` so `data/*.schema.json` ships in the wheel alongside `data/*.yaml`.

### Layer 2: Code consumes the schema

Add a small loader in `usai_harness/config.py`:

```python
def load_project_config_schema() -> dict:
    """Return the project-config JSON Schema as a dict."""
    path = Path(__file__).resolve().parent / "data" / "project_config.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))
```

Replace the hand-maintained `_KNOWN_PROJECT_FIELDS` frozenset with a derived value:

```python
def _known_project_fields() -> frozenset[str]:
    schema = load_project_config_schema()
    return frozenset(schema.get("properties", {}).keys())

_KNOWN_PROJECT_FIELDS = _known_project_fields()
```

Keep the procedural type checks in `load_project_config()` as-is for now — they are doing data-dependent validation the schema cannot. The change here is that the *field list* lives in the schema artifact, not in a Python literal.

For the unknown-field warning case, change the ignore-and-warn behavior to a hard error. The schema declares `additionalProperties: false`; the harness should match that contract. The current "log warning, ignore field" pattern is the source of the schema-leak ("the harness silently drops unknown fields, so we have to document which fields are known"). With the change: unknown fields raise `ConfigValidationError` with a message naming the unknown field, the schema URL (`$id`), and the valid field list. Update tests accordingly.

This is a **breaking change** for any consumer that has unknown fields in their project YAML. The 0.5.0 reconciliation work just landed; bundling this with 0.6.0 makes the breakage visible in one release boundary instead of two. Note in the CHANGELOG under a `### Breaking` heading.

### Layer 3: CLI subcommands

Add `usai-harness schema project-config`:

- Default `--format json` prints the schema verbatim.
- `--format yaml` prints a YAML representation (use `yaml.safe_dump` on the loaded dict).
- `--format markdown` prints a human-readable table: field name, type, required, default, description (pulled from each property's `description` field). Useful for embedding in docs that need a snapshot, while making clear the canonical artifact is the JSON.
- The subcommand reads the same artifact `load_project_config_schema()` returns; no duplication.

Add `usai-harness validate-config <path>`:

- Loads the YAML at `<path>`.
- Validates against the schema using `jsonschema` (add to optional dependency group; lazy-import in the handler so the harness still imports without it). If `jsonschema` is not installed, the handler prints a clear message and exits non-zero.
- On success: prints `OK: <path> validates against project_config_v1.` Exits 0.
- On failure: prints each validation error with field path and reason. Exits 1.
- Does NOT require a user-level catalog, does NOT resolve model names against any catalog, does NOT require credentials. This is pure schema validation, separable from runtime config-loading. Document this in `--help` text so users understand `validate-config` catches schema problems but `load_project_config` (called at workload time) catches catalog and family-catalog problems.

Wire both into `cli.py` and `setup_commands.py` following the existing handler patterns. Add `jsonschema` to a new `[validation]` extras group in `pyproject.toml` so installing it remains optional for users who only run workloads.

### Layer 4: Bootstrap template fix

Edit `usai_harness/templates/usai_harness.yaml.template`. Drop the `project:`, `ledger_path:`, and `log_dir:` lines. Replace with a top-of-file comment block:

```yaml
# Project configuration for the USAi Harness.
# Schema: usai_harness/data/project_config.schema.json
# IDE support: add `# yaml-language-server: $schema=<schema $id>` for autocomplete.
# Validate this file: `usai-harness validate-config <path-to-this-file>`
# Project name: {project_name}  (informational; the harness does not consume this)

provider: {provider_name}

# Pool of models available to this project. Each name must exist in the
# harness catalog. Run `usai-harness list-models` to see what is currently
# advertised, or `usai-harness discover-models` to refresh from the live
# endpoint. Per-model overrides (e.g. `temperature: 0.1`) go as nested keys.
{models_block}

default_model: {default_model_name}

# Concurrency: number of async workers pulling from the request queue.
workers: 3
```

The harness manages `cost_ledger.jsonl` and `logs/` directly; project-config does not configure their paths. If a future task adds configurable paths, that is a schema change with its own ADR.

Update `setup_commands.py` `handle_project_init()` if needed so the template substitutions still work after the field removals. The `{project_name}` placeholder remains, just inside a comment now.

### Tests

New file `tests/test_project_config_schema.py`:

- Schema file loads as valid JSON Schema (use `jsonschema.Draft202012Validator.check_schema`).
- A minimal valid project config validates clean.
- Each field type that the procedural code checks today has at least one positive and one negative schema test.
- An unknown top-level field fails with `additionalProperties` error.
- `model` and `models` together fail.

New file `tests/test_validate_config_command.py`:

- Validates a known-good fixture YAML, exits 0.
- Validates a fixture YAML with an unknown field, exits 1, error message names the field.
- Missing `jsonschema` extra produces a clear error message and non-zero exit (mock the import).

Update existing `tests/test_project_init.py`:

- Bootstrapped `usai_harness.yaml` round-trips through `validate-config` with exit 0. This is the regression test for the template bug. Without this test, the template can drift again.

Update existing `tests/test_config.py`:

- The unknown-field-warning test becomes an unknown-field-error test (breaking change documented in CHANGELOG).

### Documentation

- `docs/api-reference.md`: add a "Project config schema" section linking to the JSON file path and the two new CLI subcommands. Do not duplicate the schema content in markdown — the schema artifact is the source of truth.
- `docs/srs.md`: update the project-config section to reference the schema artifact and the validate-config command.
- New ADR: `docs/adr/ADR-015-project-config-schema-as-artifact.md`. Documents the architecture, the breaking change to unknown-field handling, the relationship to ADR-011 (project config) and ADR-013 (project bootstrap TEVV), the rationale for JSON Schema specifically (machine-readable, IDE tooling, language-agnostic), and the explicit out-of-scope list (the schema does not encode catalog membership, family-catalog parameter ranges, or credentials backend kwargs — those stay in code because they are data-dependent).
- CHANGELOG entry under `[Unreleased]`. Include a `### Breaking` subheading for the unknown-field-error change with a one-liner migration note ("project YAMLs with unknown fields now fail at load; remove them or upgrade to a recognized field. Run `usai-harness validate-config <path>` to find them.").

---

## What NOT to do

- Do NOT encode catalog membership in the schema. The schema validates structure; the catalog validates identity. Keep them separate.
- Do NOT encode family-catalog parameter acceptance in the schema. Same reason — schema is structural, family catalog is data.
- Do NOT make `jsonschema` a hard dependency. The harness's three hard deps (`httpx`, `python-dotenv`, `pyyaml`) stay three. `jsonschema` is an extra group, lazy-imported in the validate-config handler.
- Do NOT modify any downstream repo (federal-survey-concept-mapper or otherwise) as part of this task. Downstream README updates that consume the new authoritative artifacts are a separate task whose content depends on this one shipping.
- Do NOT touch `_apply_live_catalog`. That is the 0.5.0 reconciliation territory; this task is project-config schema only.
- Do NOT bump the schema $id within this release. v1 ships in 0.6.0. Future bumps go in their own ADRs.

---

## Verification

```
cd /Users/brock/Documents/GitHub/usai-harness
python -m pytest tests/ -v
```

All existing tests pass after the unknown-field-error update. New test files pass. `seldon verify` clean.

Manual smoke:

```
usai-harness schema project-config --format markdown   # human-readable
usai-harness schema project-config | python -c "import json,sys; json.load(sys.stdin)"   # parses
mkdir -p /tmp/usai-smoke && cd /tmp/usai-smoke
usai-harness project-init --models gemini-2.5-flash --default gemini-2.5-flash
usai-harness validate-config usai_harness.yaml   # exits 0; no unknown-field warnings on next workload load
```

The bootstrapped YAML must validate clean. If it does not, the template fix is incomplete.

---

## After completion

1. `seldon cc complete cc_tasks/2026-04-29_project_config_schema_artifact.md`
2. Run release sequence for 0.6.0 when convenient. Note the breaking-change subsection in the CHANGELOG.
3. Open a follow-on CC task in the federal-survey-concept-mapper repo: update v2/README.md to reference `usai-harness schema project-config` and `usai-harness validate-config` instead of inlining schema knowledge. The bootstrap procedure can collapse to: `usai-harness discover-models && usai-harness project-init --models gemini-2.5-flash,claude_4_5_sonnet --default gemini-2.5-flash && usai-harness validate-config usai_harness.yaml && python src/core/t3_smoke_test.py`. That follow-on is content-dependent on this task shipping; do not bundle.
4. Open a parking-lot note for IDE tooling: publish the schema $id as a resolvable URL (GitHub Pages or a release asset) so the `# yaml-language-server` directive actually resolves for users with the YAML extension installed. Not blocking; nice-to-have.
