# ADR-011: Project Configuration File Convention

**Status:** Accepted
**Date:** 2026-04-28

## Context

The harness today supports project-specific configuration through a single YAML file whose path is passed explicitly to `USAiClient(config_path=...)`. There is no convention for what that file is named or where it lives in a consuming project. The first downstream adopter (the federal-survey-concept-mapper) hit this immediately: the natural impulse was to invent a project-specific config name and structure for that project's use, which would have to be reinvented for the next project, and the next.

The harness exists to factor out infrastructure work that would otherwise be reimplemented per project. An undefined config convention pushes the reimplementation tax back onto every consumer. Adopters end up with bespoke config schemas, bespoke loaders that translate them into `ProjectConfig`, and bespoke documentation explaining the deviation. The factory pattern collapses.

The harness's model and provider catalog already lives at a known path (`configs/models.yaml` in the repo, augmented by a user-level catalog per ADR-009). The project config is the missing peer. There needs to be one named file at one known location that every consuming project uses.

## Decision

Adopt the industry-standard pattern for tools whose configuration is structurally non-trivial: a single named YAML at project root, no dot prefix.

### File location and name

The harness defaults to reading `usai_harness.yaml` from the project's current working directory. This is a project-root convention, matching how `mkdocs.yml`, `docker-compose.yml`, and `pre-commit-config.yaml` are positioned by their respective tools.

A non-default path is selectable via:
- `USAiClient(config_path=<path>)` for library use.
- `--config <path>` for any future CLI command that operates on a project config.

The dot-prefix variant (`.usai_harness/config.yaml` or `.usai_harness.yaml`) is rejected. Hidden directories suit tool-internal state (`.git`, `.tox`, `.pytest_cache`) where the user's interaction is mediated by the tool. The project config is the user's primary editable artifact for the harness; hiding it is hostile.

The TOML alternative via `pyproject.toml [tool.usai_harness]` is rejected for this use case. TOML in `pyproject.toml` works well for small, lint-style configs (ruff, mypy strict flags, black line length). The harness's project config is infra-shaped: nested model pool, output paths, worker counts, optional credential backend overrides. YAML's hierarchy reads more clearly for this shape, and YAML is already the file format in use elsewhere in the harness.

### Discovery rule

When `USAiClient` is instantiated without an explicit `config_path`:

1. Look for `usai_harness.yaml` in the current working directory.
2. If absent, fall back to the existing default behavior (use the harness's default model from the catalog with default `ProjectConfig` values).

The CWD-only discovery rule is intentional. Walking the filesystem upward to find a project root introduces ambiguity in monorepos and pip-installed contexts. If a project wants to use the convention, the script that runs `USAiClient` runs from the project root, or passes `config_path` explicitly. This matches how `docker-compose` and `mkdocs` resolve their files.

### Schema

The schema is documented in detail in ADR-012 (model pool) and the SRS. This ADR fixes the location and name only. Existing single-`model:` configs (from before ADR-012 lands) remain readable through the backward-compat shim defined in ADR-012.

## Consequences

Every project that adopts the harness gets the same config layout. New projects bootstrap with `usai-harness project-init` (defined in ADR-013), which creates `usai_harness.yaml` at project root populated with sensible defaults. Existing projects can adopt the convention by moving or renaming their existing config to match.

The federal-survey-concept-mapper smoke test files (`config/harness_concept_mapper.yaml` and the bespoke multi-section schema invented for that project) become obsolete. They get deleted when the concept mapper adopts the convention via `project-init`.

The harness gains documentation responsibility for one canonical config file. The README quickstart, the SRS, and the user guide all reference `usai_harness.yaml` by name. There is no per-project naming question to answer.

The downside is a project that has multiple harness-using subdirectories (one harness call from `pipeline_a/` and another from `pipeline_b/`, each wanting different settings) needs to either run from those subdirectories or pass `--config` explicitly. This is acceptable. The simple case stays simple, the complex case stays explicit.
