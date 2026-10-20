# CC Task: Live-catalog merge reconciliation + halt on dropped referenced models

**Date:** 2026-04-29
**Repo:** `/Users/brock/Documents/GitHub/usai-harness`
**Targets release:** 0.5.0 (NOT 0.4.0 — 0.4.0 is code-complete and awaiting tag; this is a follow-on)
**Priority:** Blocks the federal-survey-concept-mapper v2 confirmation run. Discovered 2026-04-29 during T3 smoke test execution on the work machine.

---

## Goal

Fix the live-catalog merge layer in `usai_harness/config.py` so it (a) reconciles renamed models using the family-catalog alias table before declaring them dropped, and (b) halts at config-load time when a model that is *referenced* (as `default_model`, as a project-config pool member, or as the user-level `default_model`) is dropped without a reconciliation match. Silent fallback to a different model corrupts controlled-variation experiments and must stop.

---

## Background — what's broken right now

`ConfigLoader._apply_live_catalog()` in `usai_harness/config.py` performs the seed-catalog → live-catalog merge. The current behavior, observed on the work machine 2026-04-29:

1. The seed catalog had `claude-sonnet-4-5-20241022` (the dated vendor identifier).
2. The live USAi endpoint advertises the same model as `claude_4_5_sonnet` (the USAi-mapped alias).
3. The merge dropped `claude-sonnet-4-5-20241022` because it was not in the live catalog.
4. The user-level `default_model` was `claude-sonnet-4-5-20241022`. The merge silently fell back to `claude_4_5_opus`.
5. A downstream project config (`v2/usai_harness.yaml`) referenced `claude-sonnet-4-5-20241022` as a pool member. That member was silently dropped, leaving the project pool with one rater. Two-rater downstream code then failed with a misleading "pool has 1 member" error.

The 0.4.0 family catalog already maps both `claude-sonnet-4-5-20241022` and `claude_4_5_sonnet` to the same family key (`claude-sonnet-4`). The merge layer does not consult the family catalog. It should.

The seed-catalog drop warning is appropriate. The silent default fallback is not. The project-config pool drop with no warning is not.

---

## What "done" looks like

1. The merge layer reconciles seed-side names against live-side names through the family-catalog alias table. When seed name S and live name L map to the same `(provider, family_key)`, S is treated as renamed to L, the seed entry's accounting fields (cost, context window) are carried over to L, and a single INFO-level log line records the rename: `seed model 'S' renamed to live name 'L' via family key 'K'`.
2. A model is "referenced" if it appears as: the catalog-level `default_model`, a project-config pool member (`models:` list), or a project-config `default_model`. Referenced models that are dropped *without* a reconciliation match cause `ConfigValidationError` at config-load. The error names the dropped model, the live catalog path, and instructs the user to run `usai-harness discover-models` to refresh the catalog and `usai-harness list-models` to see what is actually advertised. No silent fallback.
3. Project-config pool members go through the same reconciliation. If a pool member's name was renamed live-side, the project config silently picks up the live name (one INFO log) so the user does not have to chase rename churn through their config files.
4. A new test file `tests/test_catalog_merge_reconciliation.py` covers: rename matches via family alias, rename succeeds with cost/context carryover, dropped-but-referenced raises, dropped-and-not-referenced is just a warning (current behavior preserved), unknown alias on both sides falls through to dropped (current behavior preserved).
5. The existing dropped-models warning in `_apply_live_catalog` is kept for the unreconcilable case but its message updated to include the suggested remediation (run `discover-models`, run `list-models`).
6. CHANGELOG entry under `[Unreleased]`.

---

## Implementation notes (read before designing)

The relevant code is in `usai_harness/config.py`:

- `FamilyCatalog.family_key(provider, name)` — already exists, returns the family key or None
- `ConfigLoader._apply_live_catalog()` — current merge logic
- `ConfigLoader.load_project_config()` — project-side validation, calls `_validate_pool()`

The reconciliation algorithm:

```
For each seed model S in self._models that is NOT in `authoritative` set:
    seed_family_key = family_catalog.family_key(S.provider, S.name)
    if seed_family_key is None:
        # Unknown to family catalog — cannot reconcile, drop as before
        continue
    For each (live_provider, live_name) in `authoritative`:
        if live_provider != S.provider:
            continue
        live_family_key = family_catalog.family_key(live_provider, live_name)
        if live_family_key == seed_family_key:
            # Match — record rename, carry seed accounting forward
            new_models[live_name] = ModelConfig(name=live_name, ...,
                cost_per_1k_input_tokens=S.cost_per_1k_input_tokens, ...)
            renames[S.name] = live_name
            break
```

After reconciliation, the "referenced and dropped" check:

```
unreconciled_drops = {seed_name for seed_name in seed_model_ids
                     if seed_name not in new_models
                     and seed_name not in renames}
if self._default_model_name in unreconciled_drops:
    raise ConfigValidationError(
        f"default_model '{self._default_model_name}' was dropped by the "
        f"live catalog merge and could not be reconciled to a live name "
        f"via the family catalog. The live catalog at {catalog_path} "
        f"does not advertise this model. Run `usai-harness discover-models` "
        f"to refresh the catalog, then `usai-harness list-models` to see "
        f"what is currently advertised, then update your default_model."
    )
if self._default_model_name in renames:
    log.info("default_model '%s' renamed to '%s' via live catalog reconciliation.",
             self._default_model_name, renames[self._default_model_name])
    self._default_model_name = renames[self._default_model_name]
```

For project-config pool members, do the rename substitution inside `_collect_pool_specs` or `_validate_pool` (whichever you decide is cleaner) so the rest of `load_project_config` operates on live names. Document the choice in the docstring.

---

## What NOT to do

- Do NOT introduce string-similarity (Levenshtein, fuzzywuzzy, etc.) matching. Reconciliation goes through the family-catalog alias table only. The alias table is the curated, citable source. String similarity would silently match `claude_4_5_sonnet` to `claude-3-5-sonnet` and that is exactly the kind of failure mode being eliminated here.
- Do NOT add catalog-mutation side effects. Reconciliation is a read-only resolution at load time. The user-level `models.yaml` is not rewritten.
- Do NOT extend the family-catalog schema. The existing `provider_aliases` table is sufficient. If a model in this discussion is missing from the alias table, add the alias row in `families.yaml` as part of this task — do not invent a new table.
- Do NOT change the behavior for unreconcilable drops of *unreferenced* models. The current warning is correct for that case.
- Do NOT touch the v2 confirmation-run repo as part of this task. That is a separate CC task.

---

## Verification

```
cd /Users/brock/Documents/GitHub/usai-harness
python -m pytest tests/ -v
```

All existing tests pass. New tests in `tests/test_catalog_merge_reconciliation.py` pass. `seldon verify` clean.

Then a manual smoke: with a user-level `models.yaml` whose live providers list `claude_4_5_sonnet` (no dated identifier) and a seed `models` block that has `claude-sonnet-4-5-20241022` with default_model set to it, instantiating `ConfigLoader()` should log a single `INFO` line recording the rename and `get_default_model().name` should return `claude_4_5_sonnet`. The same scenario with the seed default_model set to a model that is neither in the live catalog nor reconcilable via family alias should raise `ConfigValidationError` with the prescribed message.

---

## After completion

1. `seldon cc complete cc_tasks/2026-04-29_catalog_merge_reconciliation.md`
2. Note in the next handoff that 0.5.0 now contains the merge-reconciliation fix and is awaiting tag (or, if release sequence is run, that 0.5.0 is shipped).
3. The federal-survey-concept-mapper v2 README pool-config section can be simplified once 0.5.0 is installed on the work machine — pool members can use either the dated identifier or the live alias and the harness will reconcile. Do NOT change the v2 README in this task; that is a separate CC task whose content depends on 0.5.0 being available.
