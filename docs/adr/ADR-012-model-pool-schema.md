# ADR-012: Model Pool Schema in Project Configuration

**Status:** Accepted
**Date:** 2026-04-28

## Context

The current `ProjectConfig` binds one client to one model. A consuming project that needs multiple models (multi-rater ensembles, model-comparison studies, primary plus fallback) must either instantiate multiple clients with separate config files or work around the schema some other way. The federal-survey-concept-mapper hit this on its first integration attempt: Stage 1 classification uses two raters from different model families, and the only path forward was a bespoke multi-section YAML with one `ProjectConfig` per section, loaded via tempfile per client. That worked but it is the wrong pattern. It pushes config-shape decisions onto every consumer.

The USAi reality reinforces what the right pattern looks like. USAi serves many models behind a single endpoint with a single API key. The provider does not change between models. The only thing that changes per call is the model identifier. The current schema treats this as N independent providers when it is one provider with N model targets.

A correct schema declares the project's model pool once, validates each pool member against the harness catalog at load time, and lets any task in the project select any model from the pool at call time. The default model field names which member is used when a task does not specify.

This is also the schema needed for ADR-013 (TEVV-on-bootstrap). The bootstrap TEVV runs one round-trip against the project's default model. That requires the config to declare a default. Without a pool concept, "default" has no meaning beyond "the only model."

## Decision

`ProjectConfig` carries a list of models, not a single model.

### Schema

```yaml
project: <name>
provider: <provider_name>
workers: <int, default 3>

models:
  - name: <model_id_from_catalog>
    # Optional per-model overrides. Defaults come from the catalog entry.
    # temperature: 0
    # max_tokens: 4096
    # system_prompt: null
  - name: <another_model_id>

default_model: <one of the model names listed above>

# Output paths (all optional, with sensible defaults)
ledger_path: cost_ledger.jsonl
log_dir: logs

# Optional credentials backend override (defaults to dotenv)
credentials:
  backend: dotenv  # or env_var, or azure_keyvault
```

### Validation rules at load time

1. Every `models[].name` must exist in the merged catalog (repo `configs/models.yaml` plus user-level overrides per ADR-009). Unknown models fail loud with the list of known models.
2. `default_model` must be one of `models[].name`. If `default_model` is omitted and there is exactly one model in the pool, that one is the default. If `default_model` is omitted and there are multiple, fail loud.
3. Per-model `temperature` overrides must fall within that model's `temperature_range` from the catalog. Validation is per-model, not against the default.
4. Per-model `max_tokens` overrides must not exceed that model's `max_output_tokens` from the catalog.
5. The `provider` field at project level must match the `provider` field on every model in the pool. Cross-provider pools are rejected; if a project genuinely needs cross-provider work, it instantiates multiple clients (one per provider). USAi's "one key, many models" reality is the common case and the one this schema optimizes for.

### Per-task model selection

`client.batch(tasks, ...)` already accepts `model` as an optional field on each task dict (see `client.py:_build_tasks`). The pool refactor extends the validation:

- A task's `model` field, if present, must be one of the pool members. Tasks targeting a non-pool model fail at task-build time with a clear error.
- A task's `temperature` override is validated against the *task's chosen model*, not against the default model. The current code validates against `self.config.temperature` only and does not re-check ranges per task; the refactor makes per-task validation explicit.
- `client.complete()` gains the same per-call validation. The `model` parameter must be a pool member.

### Backward compatibility

Existing configs with a single `model:` field (the pre-ADR-012 schema) are treated as a one-element pool with that model as default. The loader detects the legacy form and translates it. The legacy form emits no warning in 0.2.0 since the harness has zero external adopters yet at this writing; the translation is silent. If a future external adopter materializes, a deprecation warning can be added in 0.2.x.

### What does not change

- The `ModelConfig` dataclass itself is unchanged. Pool members are `ModelConfig` instances pulled from the catalog.
- The catalog file structure (`configs/models.yaml` + user-level catalog) is unchanged.
- The credential resolution chain (ADR-008) is unchanged.
- The transport layer is unchanged.
- The cost ledger and call log formats are unchanged.

## Consequences

A project declares its rater pool once and any code path can address any rater. Multi-rater ensembles, A/B testing, primary-with-fallback, model migration during a long-running job — all become per-task choices, not multi-client gymnastics.

The validation logic in `config.py` grows. Instead of one model to validate, the loader walks the pool, validates each member against the catalog, validates per-member overrides against per-member ranges, and validates the default_model selection. Tests for `config.py` grow correspondingly: pool with one member, pool with three members, pool with invalid member, pool with out-of-range temperature on one member, pool with mismatched providers, missing default_model with multi-member pool, legacy single-`model` config.

The validation logic in `client.py` grows. `_build_tasks` and `complete()` add per-task model and temperature validation. Tests for the worker pool's per-task error path grow correspondingly: task with non-pool model, task with valid model but out-of-range temperature override.

The federal-survey-concept-mapper's smoke test, when rewritten against the new schema, instantiates one `USAiClient` for the whole pipeline. Stage 1's two raters become two task-level model selections within `client.batch()`, not two separate clients. The bespoke multi-section YAML deletes.

The cost ledger and call log gain implicit per-model attribution because each entry already records the model used. Per-model cost reports work without schema changes; the existing `cost-report` command's `--model` filter continues to function.

## Amendment, 2026-04-29 — parameter validation removed

Items 3 and 4 of *Validation rules at load time* are reversed. The harness no longer enforces per-model `temperature` or `max_tokens` ranges at config-load time, and the matching per-call validation in `client.complete()` and `client._build_tasks()` is removed. Pool members carry whatever per-model fields the user wrote; those fields are forwarded to the transport unchanged. Whatever is omitted is not sent.

The justification is that provider behavior is the actual contract. GPT-5 and Claude reject the `temperature` parameter entirely. Gemini Flash accepts `temperature` in `[0, 1]`. Some providers accept `[0, 2]`. The catalog's `temperature_range` could not capture this without becoming a per-model decision table that drifts on every provider release. A config that passed harness validation but failed at the provider gave the user a debugging trail two layers deep; a config that goes straight to the API gives the user the provider's actual error message in the call log immediately. Catalog entries are now identity and accounting, not behavior.

The remaining load-time validations are unchanged: `models[].name` must exist in the merged catalog (item 1), `default_model` must be a pool member (item 2), and `provider` must match every pool member's catalog provider (item 5). Per-task `model` overrides are still validated against the pool at task-build time. The legacy single-`model:` translation is unchanged.

The `temperature_range` and `max_output_tokens` fields are removed from `ModelConfig` and from every entry in `configs/models.yaml`. User-level catalogs that still carry these fields remain readable; the loader ignores extra fields rather than rejecting them.
