# Operations Guide — usai-harness

**Version:** 1.0
**Date:** 2026-04-24

This guide covers running and maintaining the usai-harness. It is written for researchers who use the library from their projects, not for developers modifying the library itself. For design rationale see the ADRs. For requirements see the SRS.

## 1. First-Time Setup

### 1.1 Install

```bash
pip install usai-harness
```

If your environment supports the LiteLLM backend and you want the broader provider catalog:

```bash
pip install "usai-harness[litellm]"
```

If you use Azure Key Vault for secrets:

```bash
pip install "usai-harness[azure]"
```

### 1.2 Initialize

```bash
usai-harness init
```

You will be prompted for:

1. Provider name (press Enter to accept `usai` as default)
2. Base URL for the provider (find it in the USAi console under the API tab)
3. API key (echoed as `*` while typing; a `Key saved: ****<last4>` confirmation prints after capture)

Paste the base URL exactly as the provider documents it. The harness auto-detects the API path prefix during setup by probing `/api/v1`, then `/v1`, then the bare URL; whichever returns a successful `/models` response wins, and that resolved URL is what gets stored. If you paste a URL that already includes the prefix, the bare-prefix probe matches and the URL is stored unchanged.

The command writes your credentials to the user-level config directory, fetches the live model list from the resolved URL, and runs a test call to confirm everything works. On success you see the detected URL, the list of available models, and a sample response. If every probe fails (the endpoint is unreachable, or none of the probed prefixes return 200), `init` warns, prompts you for a default model ID, and writes credentials anyway so you are not stuck. Run `usai-harness discover-models` later to populate the catalog when the endpoint is reachable.

Re-running `init` is safe. It does not accumulate state.

### 1.3 Verify your setup

```bash
usai-harness verify
```

This runs an end-to-end check against every configured provider: credential resolves, endpoint is reachable, model catalog returns, test call succeeds. Useful to confirm everything works before depending on it in a real job.

Once verify passes, the fastest way to confirm the harness works from your own code is to run `python docs/examples/01_quickstart.py`. It is a thirty-line script that issues one completion through the public Python API.

### 1.4 Bootstrap a project

Run `usai-harness project-init` once per project, from the project's root directory. The command:

1. Creates `usai_harness.yaml` (if absent) with the project name from the directory name, the provider and default model from the user-level catalog, and a one-element pool you can extend later.
2. Creates `output/`, `output/logs/`, `tevv/`, `scripts/`, `inputs/`, and `outputs/` directories.
3. Writes `scripts/example_batch.py`, a runnable demonstration of `client.batch()` against a small input file. Edit it freely or replace it with your real job.
4. Appends entries to `.gitignore` for the data files (`output/cost_ledger.jsonl`, `output/logs/`). The `.yaml` config is intended to be committed; the per-run data is not.
5. Runs one TEVV smoke round-trip against the project's default model with the trivial prompt "Reply with the word OK." and writes a markdown report to `tevv/init_report_<UTC_timestamp>.md`.

`project-init` is idempotent. Existing `usai_harness.yaml` and `scripts/example_batch.py` are left in place. Existing `.gitignore` lines are not duplicated. Each run produces a fresh timestamped TEVV report; the `tevv/` directory accumulates one report per run, which is a regression history per project.

The exit code is 0 on TEVV pass and 1 on TEVV fail. A failed TEVV does not roll back created files; the layout is still useful for diagnosis and the report records the failure mode.

### 1.5 Multi-rater bootstrap

For a project that needs more than one rater, declare the pool inline at bootstrap. No post-bootstrap YAML editing required:

```bash
usai-harness project-init \
    --models gemini-2.5-flash,claude-sonnet-4-5-20241022 \
    --default gemini-2.5-flash
```

`--models` is a comma-separated list of catalog model names. Each must exist in the merged catalog; run `usai-harness list-models` first to see the available names. `--default` names the pool member used when a task does not specify a model.

If you run `project-init` without flags from an interactive shell, it shows the catalog as a numbered list and prompts for the pool selection (and the default). CI and scripted bootstraps must pass the flags to avoid hanging.

Cross-provider pools are rejected at bootstrap (ADR-012). Pick from a single provider, or run `project-init` twice with separate pools.

Per-model parameter overrides (e.g. `temperature: 0.1` on a specific Gemini entry) are not flag-driven. Bootstrap with `--models`, then add the override as a one-line edit to the generated `usai_harness.yaml`. Project-specific configuration belongs in version control; the bootstrap command should not be regenerating it.

### 1.6 Project configuration schema

The `usai_harness.yaml` written by `project-init` is the file your project edits to declare its model pool and per-project settings. The schema:

```yaml
project: rater-ensemble
provider: usai

models:
  - name: claude-sonnet-4-5-20241022
    # Optional per-model overrides; uncomment to set.
    # temperature: 0
    # max_tokens: 4096
  - name: claude-opus-4-5-20250521
  - name: gemini-2.5-flash

default_model: claude-sonnet-4-5-20241022

workers: 3
batch_size: 50

# Project-default request parameters (validated against default_model's ranges).
temperature: 0.0
max_tokens: null

# Output paths
ledger_path: output/cost_ledger.jsonl
log_dir: output/logs

# Optional credential backend override (defaults to dotenv)
credentials:
  backend: dotenv              # dotenv | env_var | azure_keyvault
```

Every pool member must exist in the merged catalog (run `usai-harness discover-models` to refresh from the live endpoint). Cross-provider pools are rejected. Per-pool-member `temperature` and `max_tokens` overrides are validated against that member's catalog ranges, not the default model's. Per-task `model` and `temperature` overrides in `batch()` and `complete()` are validated against the task's chosen model at task-build time, so a typo or out-of-range value fails before any HTTP traffic.

Older configs that declared a single `model:` field translate automatically to a one-element pool. Configs declaring both `model:` and `models:` are rejected at load.

## 2. Key Rotation

### 2.1 USAi keys (DotEnv backend, default)

USAi keys expire seven days after issue. When your key expires or is about to:

1. Get a fresh key from the USAi console.
2. Run `usai-harness init` and paste the new key when prompted.
3. Done. Every project on your machine now uses the fresh key on its next call.

No need to touch any project. No need to find and update multiple `.env` files. The user-level config handles it.

If you prefer to edit the file directly:

- Linux/macOS: `~/.config/usai-harness/.env`
- Windows: `%APPDATA%\usai-harness\.env`

### 2.2 Azure Key Vault (Azure backend)

Azure Key Vault rotates keys transparently for you. The harness reads the current value from the vault on each call. There is nothing to refresh on the client side.

If your vault secret name or URL changes, update your project configuration and re-run `usai-harness verify`.

### 2.3 Environment variable (EnvVar backend)

Environment variables are set by your CI system, container orchestrator, or shell profile. Follow the rotation process of whatever system sets them. The harness reads whatever is in the environment at call time.

## 3. Running Batch Jobs

### 3.1 Before starting a long job

Always run:

```bash
usai-harness verify
```

This takes about thirty seconds and confirms every provider works end-to-end. If you are about to launch a job that will run overnight, over a weekend, or through business hours when you are not watching, this is the difference between finding out something broke Monday morning and finding out Friday afternoon.

Check your key lifetime. If the USAi key was issued five days ago and your job will run three days, refresh the key now rather than letting the job halt partway through.

After a `pip install --upgrade usai-harness`, re-run `usai-harness project-init` from the project root. It will leave your config and example script in place, deduplicate gitignore entries, and produce a fresh TEVV report under `tevv/`. The accumulated `tevv/init_report_*.md` files form a regression history: every harness version your project has run against has a recorded round-trip showing it worked at adoption time. If the new harness version regresses, the smoke test catches it before the upgrade ships into a long-running job.

### 3.2 During a job

The harness writes progress to two files:

- The call log (structured JSON, one entry per call)
- The cost ledger (one entry per successful call)

Both are in the project's working directory by default. You can tail them to watch progress:

```bash
tail -f logs/calls.jsonl
```

The call log flushes after every write, so you see activity in near real time.

### 3.3 If a job halts

Two causes for a clean halt:

1. **Authentication failure (HTTP 401 or 403).** The key expired or was revoked. Refresh it per Section 2, then resume the job. The harness preserves checkpoint state; completed tasks are not re-run.
2. **Unrecoverable transport error.** Network failure, endpoint down, config problem. Read the error message, fix the underlying cause, resume.

Job resumption is handled by the calling code. The harness preserves the state; your project code decides when to resume. See the API reference for details on the resume pattern.

### 3.4 Rate-limit behavior

The harness adapts to provider rate limits automatically. On HTTP 429, it slows down by 25 percent. On sustained success, it speeds back up by 5 percent per window. You do not need to tune this. Watch the post-run report for observed rate-limit events if you want to understand what the provider was doing.

## 4. Reports and Monitoring

### 4.1 Post-run report

At the end of every batch call, the harness emits a summary: call count, success rate, total tokens, total cost, rate-limit events, and any model-echo mismatches. Read it. If the success rate is below 100 percent or if any model-echo mismatches show up, the report tells you which tasks need attention.

### 4.2 Cost reporting across jobs

```bash
usai-harness cost-report
```

Aggregates the cost ledger by project, job, and model over a user-specified time range. Useful for monthly reporting, budget tracking, or comparing model costs across similar workloads.

Options:

```bash
usai-harness cost-report --project my-project
usai-harness cost-report --job my-batch
usai-harness cost-report --since 2026-04-01 --until 2026-04-30
```

Since the ledger is append-only, historical numbers stay stable. If cost rates change in `configs/models.yaml`, historical entries keep the rate that applied at their time of call.

### 4.3 Reading the call log

Each line in `logs/calls.jsonl` is a JSON object with timestamp, project, job, task ID, model requested, model returned, token counts, latency, and status. To find failed calls in a specific job:

```bash
grep '"status":"error"' logs/calls.jsonl | grep '"job":"my-batch"'
```

For anything more complex, use `jq`:

```bash
jq 'select(.status=="error") | {task_id, error}' logs/calls.jsonl
```

## 5. Adding Providers and Models

### 5.1 Adding a new provider

```bash
usai-harness add-provider openrouter
```

Prompts for base URL and key. Tests reachability. Fetches the model catalog. Updates the user-level configuration. Does not affect any previously configured provider.

The new provider is immediately available in your code:

```python
async with USAiClient(project="my-project") as client:
    response = await client.complete(
        messages=[...],
        model="openrouter/some-model-id",
    )
```

### 5.2 Refreshing the model catalog

Providers add and remove models over time. If you get a "model not found" error for a model that used to work, refresh the catalog:

```bash
usai-harness discover-models
```

Refreshes the catalog for every configured provider. To refresh just one:

```bash
usai-harness discover-models usai
```

The command does not touch credentials and does not modify the repository-level `configs/models.yaml`. It only updates your user-level catalog.

To see what is currently in the merged catalog (without hitting the network), use:

```bash
usai-harness list-models
```

Add `--provider NAME` to filter, or `--format names` to get one model name per line for piping. Use this when you are setting up a multi-rater pool in `usai_harness.yaml` and need the exact name strings.

### 5.3 Customizing model presentation

If you want friendly display names or different default temperatures for specific models, edit `configs/models.yaml` in the repository or in your user-level config. These are presentation overrides. The endpoint is still the source of truth for which models exist.

Example:

```yaml
models:
  - id: meta-llama/Llama-4-Maverick-17B-128E-Instruct
    name: "Llama 4 Maverick"
    temp_default: 0.5
```

Model IDs must match exactly what the endpoint returns. That's why `discover-models` exists; it gives you the correct IDs to reference.

## 6. Security Hygiene

### 6.1 Running an audit

```bash
usai-harness audit
```

Checks three things:

1. **Gitignore coverage.** Verifies that `.env`, `cost_ledger.jsonl`, and `logs/` are covered in your project's `.gitignore`. If not, the audit tells you which lines to add.
2. **Tracked secrets.** Scans for API keys accidentally committed to git history. If any are found, the audit lists them. You will need to rotate the affected key and follow your organization's incident response procedure.
3. **Dependency vulnerabilities.** Runs `pip-audit` against your current Python environment and reports known CVEs in your installed packages.

Run `audit` before pushing a new repository to a shared remote. Run it periodically on long-lived projects.

### 6.2 What the harness already does for you

You do not need to configure any of this. It is on by default:

- API keys are scrubbed from all log output and error messages.
- YAML configuration is loaded safely (no code execution from crafted files).
- TLS verification is enforced.
- The cost ledger cannot contain prompt or response content (enforced by the data structure, not by convention).
- Full content logging requires an explicit per-job flag.

### 6.3 Reproducible installs

For environments that require deterministic installs:

```bash
pip install -r requirements.lock --require-hashes
```

The lockfile pins every dependency to a specific version and verifies cryptographic hashes. Use this in CI, in production containers, or anywhere install reproducibility matters.

## 7. Provider-specific behavior

The harness targets any OpenAI-compatible endpoint, but real endpoints diverge in how they signal failures and what they accept as inputs. The behaviors below have been observed against current endpoints and are stable enough to plan around. They are not bugs in the harness.

### 7.1 Authentication failure status codes

USAi returns HTTP 401 or 403 for an invalid API key. The harness catches both and raises `AuthHaltError`, which drains the worker pool cleanly and preserves the partial results. Gemini's OpenAI-compat endpoint returns HTTP 400 for an invalid key, with a structured JSON body containing `error.status: "INVALID_ARGUMENT"` and a message saying the key is invalid. The harness treats 400 as a non-retryable per-call failure, not as an auth halt, which means a mis-typed Gemini key produces N individual non-retryable failures (one per worker) rather than a clean halt.

Operational mitigation: run `usai-harness verify` or a single `ping` before any long-running Gemini batch. The first response will reveal an invalid key immediately. Do not rely on the pool halting partway through.

The harness deliberately does not attempt to detect auth-failure 400s by inspecting body content. Pattern matching on error message text would be fragile against provider rephrasings. It would also produce false positives on legitimate per-call 400s such as malformed bodies, unsupported parameters, or context-length exceeded, all of which Gemini also returns as 400.

### 7.2 Gemini 2.5 thinking tokens and `max_tokens`

Gemini 2.5 models reserve a portion of the response budget for internal thinking tokens before producing visible content. Setting `max_tokens` below approximately 64 on Gemini 2.5 models can cause the response content to be empty even when the call succeeds with HTTP 200. The recommended floor for Gemini 2.5 smoke tests is `max_tokens=64`. For production batches, size based on the actual content length expected plus a thinking-overhead margin.

This behavior is specific to Gemini 2.5. Earlier Gemini models and other providers do not reserve thinking tokens this way. Successful 200 responses with empty content are the diagnostic signal to raise the budget.

### 7.3 Provider model ID naming

Gemini's `/models` endpoint returns IDs in the form `models/gemini-2.5-flash` rather than the bare `gemini-2.5-flash`. The harness round-trips these correctly: `discover-models` caches them as Gemini returns them, and the live catalog merge uses the full form. Pass model IDs verbatim from the live catalog rather than typing the short form. The `model_requested` and `model_returned` log fields will both reflect the full form for Gemini calls.

### 7.4 Provider registration is interactive

`usai-harness add-provider` prompts for credentials and endpoint details interactively. There is currently no flag-based path for scripted bring-up. For now, register providers manually on each machine that needs them. Once registered, `discover-models <name>` and the rest of the CLI surface work non-interactively.

## 8. Troubleshooting

### 8.1 "No API key found" on init

The `init` command could not resolve a credential from any source. Check that you pasted the key correctly. Check that the terminal did not truncate a long key. Run `init` again and use the paste buffer rather than typing.

### 8.2 "Model not found" error

The model identifier in your code does not match any model in the live catalog. Run `usai-harness discover-models` to refresh the catalog, then check the current list with:

```bash
python -c "from usai_harness import USAiClient; import asyncio; asyncio.run(USAiClient(project='x').list_models())"
```

Or simpler, check the user-level `models.yaml` file directly.

### 8.3 Authentication failures that persist after rotation

The key was refreshed but calls still return 401. Likely causes:

1. The new key was pasted into a project-local `.env` and an old key remains in the user-level `.env`. The project `.env` takes precedence. Either remove the project `.env` or update the user-level file.
2. The Azure Key Vault secret was updated but your session is cached. Restart your Python process.
3. An environment variable is overriding the file-based credential. Check `echo $USAI_API_KEY` and `unset USAI_API_KEY` if needed.

Run `usai-harness verify` to confirm which credential source is being read.

### 8.4 Batch jobs running slower than expected

Check the post-run report for rate-limit events. If the harness tripped 429s and backed off, the average throughput will be lower than the configured rate. This is expected and correct behavior.

If no 429s occurred but throughput is still low, check the worker pool size in your project configuration. The default is 3 workers. For CPU-heavy response processing, you may need more. For strict rate limits like USAi 3/sec, more than 3 workers will not help.

### 8.5 Cost ledger disagrees with post-run report

Post-run reports are per-batch. The cost ledger is cumulative across all batches for a project. If you ran multiple batches for the same project, the ledger totals will be higher. Use `usai-harness cost-report --job JOB_NAME` to compare like with like.

### 8.6 `pip-audit` flags a dependency

If the audit reports a known vulnerability in a harness dependency or optional extra, report it as an issue. Major-version dependency bumps require regression testing before adoption.

## 9. Getting Help

For usage questions, check the README and the API reference.

For design questions, check the ADRs in `docs/adr/`.

For bugs or feature requests, file an issue on the repository with:

- What you were trying to do
- What happened
- What you expected to happen
- The output of `usai-harness verify` and the relevant slice of `logs/calls.jsonl`

Avoid pasting API keys, full prompt content, or PII into issue reports. The harness redacts these in its own output, but once content is in an issue tracker it stays there.
