# ADR-013: Project Bootstrap with TEVV Smoke Test

**Status:** Accepted
**Date:** 2026-04-28

## Context

Adopting the harness from a downstream project today requires several manual steps: install the package, create a project config in the right shape, set up credential resolution if not already done, decide where the cost ledger and logs go, validate that the whole stack works against the live endpoint, and document the version of the harness used. None of this is hard, but every adopter does it slightly differently, every adopter's first attempt has at least one mistake, and the failure modes are diffuse (wrong path, wrong key location, wrong model name, network unreachable, version skew).

The harness's purpose is to factor out infrastructure work. Bootstrap is infrastructure work. It belongs to the harness.

A separate concern: every project that adopts the harness should produce evidence that the integration works at adoption time. Federal statistical work in particular runs on documented Test, Evaluation, Validation, and Verification (TEVV) practices. A project that depends on the harness should have a recorded TEVV report from its first run, showing harness version, model used, round-trip success, and a timestamp. This becomes provenance for the project's later outputs and a regression detector if a future harness version introduces a bug.

The TEVV scope at bootstrap is intentionally narrow. It is a smoke test, not a conformance suite. One round-trip against the project's default model proves: credential resolution works, network reaches the endpoint, the model name is correct, the transport handles the response shape correctly, and the cost ledger and call log get written. That covers every category of failure that would prevent the project from running. Per-model conformance against every pool member is out of scope at bootstrap; if a project later wants that, it runs `usai-harness verify --all-models` (a separate command, opt-in, not on the bootstrap path).

## Decision

Add `usai-harness project-init` as a CLI subcommand that creates a standard project layout and runs a TEVV smoke test against the default model.

### Behavior

`usai-harness project-init` runs from the project's root directory and:

1. **Creates `usai_harness.yaml`** at project root, populated with sensible defaults: project name from the directory name, provider from the user-level config, model pool with the user-level default model as the only member, ledger and log paths in `output/`, worker count 3.

2. **Creates output directories**: `output/`, `output/logs/`, `tevv/`. The directory `tevv/` is where bootstrap reports go.

3. **Appends to `.gitignore`** at project root, adding entries for: `output/cost_ledger.jsonl`, `output/logs/`, `usai_harness.yaml` is *not* added (the config is meant to be committed; the data files are not).

4. **Creates `scripts/example_batch.py`** as a runnable demonstration of the harness API. The example reads a small input, builds tasks, calls `client.batch()`, writes a small output, and prints a one-line summary. The file is committed and intended to be read, edited, or replaced by the project author.

5. **Runs the TEVV smoke test**: a single round-trip against the project's default model with a trivial prompt. Validates that the call succeeded with HTTP 2xx, that a parseable response came back, that the cost ledger received an entry, and that the call log received an entry.

6. **Writes the TEVV report** to `tevv/init_report_<UTC_timestamp>.md`. The report records: harness version (from package metadata), Python version, OS, project root path, default model name and provider, request timestamp, response latency in ms, status code, prompt and response token counts, total cost (zero for free-credit periods), pass/fail verdict.

7. **Exits 0 on TEVV pass, 1 on TEVV fail.** A failed TEVV does not roll back created files; the layout is still useful for diagnosis. The TEVV report itself records the failure mode.

### Idempotency

Re-running `project-init` is safe and useful:

- `usai_harness.yaml` is *not* overwritten if it exists. If it exists, `project-init` reports "config exists, leaving alone" and continues.
- Directory creation is no-op if the directory exists.
- `.gitignore` entries are appended only if not already present (line-by-line check).
- `scripts/example_batch.py` is *not* overwritten if it exists.
- The TEVV smoke test runs every time. Each run produces a new timestamped report. The `tevv/` directory accumulates reports across runs; this is desirable as a longitudinal record.

The intent is that re-running `project-init` after a harness upgrade verifies nothing broke. A project that runs `project-init` after every `pip install --upgrade usai-harness` has a TEVV record of every harness version it has ever run against.

### TEVV smoke test scope

One round-trip against `default_model`. Trivial prompt: "Reply with the word OK." Trivial validation: the response contains the word "OK" (case-insensitive). The test is not measuring model behavior; it is measuring that the harness's full path works end to end.

Per-model verification across the pool is *not* part of TEVV-on-bootstrap. A TEVV run takes a few seconds, not 30+, even with multiple models in the pool. If a project wants per-model verification, it runs `usai-harness verify` (existing command, ADR-009) separately. The bootstrap path is fast and the marginal value of N model checks at bootstrap does not justify the latency.

### TEVV report format

The report is markdown for human readability. Single file per run, no append-mode. Contents:

```markdown
# TEVV Report: <project_name>
**Date (UTC):** <iso8601>
**Verdict:** PASS | FAIL

## Environment
- Harness version: 0.2.0
- Python: 3.12.x
- OS: <platform string>
- Project root: <abs_path>

## Configuration
- Provider: usai
- Default model: <model_id>
- Model pool: [<model_id>, ...]

## Smoke Test
- Prompt: "Reply with the word OK."
- Status: 200
- Latency: 412 ms
- Prompt tokens: 7
- Completion tokens: 1
- Cost (USD): 0.000000
- Response sample: "OK"

## Verdict
PASS — round-trip succeeded, cost ledger updated, call log updated.

## Provenance
- Cost ledger entry: <ledger_path>:<line_number>
- Call log entry: <log_path>:<line_number>
```

On FAIL, a `## Failure` section appears in place of `## Verdict` with the specific check that failed and the relevant exception or response body.

### Reuse of existing CLI plumbing

The smoke test reuses `usai-harness ping`'s implementation under the hood (single round-trip, default model, fast). The differences are: `project-init` runs the round-trip *as part of bootstrap*, captures the result in a report file rather than just printing, and ties it to the project's `usai_harness.yaml` configuration. `ping` remains as a standalone fast-check command for any time the user wants to verify the credential is alive.

## Consequences

Adopting the harness becomes one command. A new project runs `pip install usai-harness` (after the package is published, or `pip install -e <path>` for now), then `cd <project_root> && usai-harness project-init`, and has a working layout with documented evidence of correctness. Failures at bootstrap are explicit and recorded.

Every project that adopts the harness produces a `tevv/init_report_*.md` artifact at adoption time. This is git-committable provenance. If the project later produces results that depend on the harness, the TEVV report is the bootstrap-time evidence that the harness was working when the project started using it.

A project that upgrades the harness can re-run `project-init` to validate the upgrade. If the new harness version regresses, the TEVV smoke test catches it. The accumulated `tevv/init_report_*.md` files form a regression history per project.

The harness's adoption tax drops to near zero. Documentation no longer needs to walk a user through five manual setup steps; it documents one command.

The federal-survey-concept-mapper, when it adopts the new schema, runs `project-init` from the concept mapper root, gets the standard layout, and gets a TEVV report. The bespoke smoke test script written during the prior session is deleted; its purpose is now covered by the harness itself.

The harness gains a templates directory at `usai_harness/templates/` containing the starter `usai_harness.yaml`, the starter `example_batch.py`, and the gitignore entries. The template content is part of the package, not user-config-relative. Updating templates is a harness release concern.

## Amendment, 2026-04-29 — multi-rater pool at bootstrap

The original decision wrote a single-rater pool with the user-level default model. Any project that needed a multi-rater pool had to hand-edit `usai_harness.yaml` after `project-init` finished, which reintroduces exactly the level-3 friction the bootstrap command exists to remove. The federal-survey-concept-mapper v2 confirmation run hit this on first contact: bootstrap, smoke test fails ("pool only has one rater"), look up the canonical pool YAML in the project README, paste, save, re-run.

`project-init` now accepts pool declaration inline. Two new flags:

- `--models MODEL1,MODEL2,...` — pool members as a comma-separated list of catalog names. Each name must exist in the merged catalog; an unknown name fails loud with the catalog list.
- `--default MODEL` — must be one of `--models`. Required to skip the prompt when the pool has more than one member.

When no flags are given and stdin is interactive, `project-init` prompts: it shows the catalog as a numbered list, takes a comma-separated index selection for the pool, and (for multi-member pools) takes a single index for the default. CI and other non-interactive contexts pass `--models` and `--default` to avoid hanging.

When neither flags nor an interactive stdin are present, `project-init` keeps its original single-rater behavior with the user-level default model. Existing tests pass without modification.

Cross-provider pools are still rejected at bootstrap (ADR-012). `project-init --models claude_4_5_sonnet,alpha-model` exits 1 with a clear cross-provider error before writing any files.

Per-model parameter overrides (such as `temperature: 0.1` on a specific Gemini entry) are *not* a CLI flag. The pattern is `project-init --models gemini-2.5-flash,claude_4_5_sonnet`, then a one-line edit to the generated YAML for the override. That edit is project-specific configuration that genuinely belongs in version control, not boilerplate the bootstrap command should be regenerating.
