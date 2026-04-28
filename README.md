# usai-harness

![CI](https://github.com/brockwebb/usai-harness/actions/workflows/ci.yml/badge.svg)

**Built for USAi. Works with any OpenAI-compatible endpoint.**

A Python client library that handles the annoying parts of calling a large
language model from a research project: credentials, rate limits, retries,
cost tracking, and structured logging. Install once, set up your key once,
use it from every project on your machine.

Not a framework. Not a platform. A client library that handles your API key
so you can focus on the work.

Endpoint behavior diverges in practice; see `docs/ops-guide.md` section
"Provider-specific behavior" for known differences in auth-failure handling,
model ID naming, and per-provider parameter quirks.

## Why this exists

LLM API keys rotate. USAi keys expire every seven days. If you have five
research projects that all call the same API, each project needs the same
fresh key. Copying a `.env` file around every week is a tax on your time
and a source of security mistakes.

This library solves that. Your key lives in one place on your machine. Every
project that uses the library picks it up automatically. One rotation, every
project keeps working.

The library also handles the other parts that every project re-invents:
rate limiting, retries with backoff, cost tracking, structured logging, and
clean shutdown when a key expires mid-job.

## Quick start

```bash
pip install usai-harness
usai-harness init
cd your-project
usai-harness project-init
python scripts/example_batch.py
cat tevv/init_report_*.md
```

The `init` command (run once per machine) prompts you for your API endpoint
and key, writes them to your user config, pulls the live model list from the
endpoint, and runs a test call to confirm everything works.

The `project-init` command (run once per project, in the project root)
creates `usai_harness.yaml`, the `output/` and `tevv/` directories, and
`scripts/example_batch.py`. It then runs a TEVV smoke test against the
project's default model and writes a markdown report to
`tevv/init_report_<UTC_timestamp>.md`. Re-running is safe: it leaves your
config and example script in place, deduplicates `.gitignore` entries, and
produces a fresh report so you have evidence of every harness version your
project has run against.

After `project-init`, any Python script in the project can do this:

```python
from usai_harness import USAiClient

async with USAiClient(project="my-project") as client:
    response = await client.complete(
        messages=[{"role": "user", "content": "Hello"}],
    )
```

The client picks up `usai_harness.yaml` from the current working directory
automatically. Pass `config_path=` explicitly if your script runs from a
different location.

## Running a batch job

```python
async with USAiClient(project="my-project") as client:
    tasks = [
        {"messages": [{"role": "user", "content": f"Question {i}"}],
         "task_id": f"q_{i:04d}"}
        for i in range(100)
    ]
    results = await client.batch(tasks, job_name="my-batch")
```

Batch calls are rate-limited automatically, retry transient failures, and
write a structured log and a cost ledger as they run. If the key expires
partway through, the job halts cleanly, preserves its progress, and can be
resumed after you refresh the key.

### Multiple models per project

Declare a pool of models in `usai_harness.yaml` and pick which one each
task uses at submit time:

```yaml
project: rater-ensemble
provider: usai

models:
  - name: claude-sonnet-4-5-20241022
  - name: claude-opus-4-5-20250521
  - name: gemini-2.5-flash

default_model: claude-sonnet-4-5-20241022
workers: 3
```

```python
async with USAiClient(project="rater-ensemble") as client:
    tasks = [
        {"messages": [{"role": "user", "content": q}],
         "model": "claude-sonnet-4-5-20241022", "task_id": f"sonnet_{i}"}
        for i, q in enumerate(questions)
    ] + [
        {"messages": [{"role": "user", "content": q}],
         "model": "claude-opus-4-5-20250521", "task_id": f"opus_{i}"}
        for i, q in enumerate(questions)
    ]
    results = await client.batch(tasks, job_name="multi-rater")
```

Per-task `model` and `temperature` overrides are validated against the
chosen model's catalog entry at task-build time, so a typo or out-of-range
value fails before any HTTP traffic. Cross-provider pools are rejected;
projects that genuinely need cross-provider work instantiate one client
per provider.

### Backward compatibility

Older configs that declared a single `model:` field instead of a `models:`
list are translated automatically to a one-element pool. No changes are
required to upgrade an existing 0.1.x project to 0.2.0; running
`project-init` in an existing project will leave your config in place and
just produce a TEVV report.

### Before a long-running job

USAi keys expire seven days after they are issued. If you are about to
start a batch job that will run longer than a few hours, check your key
first:

```bash
usai-harness verify
```

If the job outlives the key, the harness will halt cleanly on the first
401 and keep the work it already finished. You can refresh the key and
resume. But a weekend job with a Tuesday-issued key can turn into a
Monday-morning surprise. The thirty-second check is worth it.

## Where your key lives

The library stores your key in a user-level config directory:

- **Linux:** `~/.config/usai-harness/.env`
- **macOS:** `~/.config/usai-harness/.env`
- **Windows:** `%APPDATA%\usai-harness\.env`

Every project on your machine reads from this location. One key, many
projects. Rotate it once, you are good everywhere.

If a specific project needs a different key, drop a `.env` in that
project's root directory. The library will use the project `.env` for
that project only and the user-level `.env` everywhere else.

CI systems and containers usually set credentials as environment
variables. The library reads those too, no file required.

## Commands

| Command | What it does |
|---------|--------------|
| `usai-harness init` | First-run setup. Prompts for endpoint and key, tests everything. |
| `usai-harness add-provider NAME` | Add another provider (for example OpenRouter, Anthropic). |
| `usai-harness discover-models` | Refresh the model list from each configured endpoint. |
| `usai-harness verify` | End-to-end health check for every provider you have configured. |
| `usai-harness ping` | Quick single-call check against the default provider. |
| `usai-harness cost-report` | Summary of tokens and costs by project, job, or model. |
| `usai-harness audit` | Security hygiene check (gitignore coverage, tracked secrets, dependency audit). |

## Multiple providers

If you want to use OpenRouter, Anthropic's API, or another OpenAI-compatible
endpoint, you can register it:

```bash
usai-harness add-provider openrouter
```

Answer the prompts for the base URL and key. Each provider keeps its own
key under its own name. When you make a call, you pick the provider in
your code or your project config.

## Configuration

Most researchers never need to edit a config file. `usai-harness init`
creates everything needed on first run.

If you want to override defaults per project, create a `usai-harness.yaml`
in your project root:

```yaml
transport: httpx     # or litellm, if installed
workers: 3           # parallel workers, default 3
```

The transport layer is pluggable. By default the library makes direct
HTTP calls using `httpx` and depends on no LLM framework libraries.
If your environment permits it, you can install the LiteLLM backend
for a broader provider catalog:

```bash
pip install usai-harness[litellm]
```

For agency environments that use Azure Key Vault for secret storage:

```bash
pip install usai-harness[azure]
```

The Azure backend reads keys directly from your vault. No local file.

## What gets logged

Every call writes a structured JSON entry to a call log with the time,
project, job, model, token counts, and status. No prompts, no responses
are logged by default. If you need full content logs for debugging, you
enable them on a single job at a time, not globally.

The cost ledger at `cost_ledger.jsonl` is append-only. It tracks tokens
and computed cost per call. It cannot contain prompts or responses by
design, so you can share it for audit or review without privacy concerns.

At the end of a batch, you get a summary report: how many calls, how
many succeeded, total tokens, total cost, any unusual rate-limit
behavior, and any mismatches between the model you asked for and the
model that answered.

## Security

The library applies safe defaults without asking:

- API keys are scrubbed from logs and error messages.
- Configuration files are loaded with `yaml.safe_load`.
- TLS verification is on. If you disable it, you see a warning on every call.
- The cost ledger structurally cannot contain prompt or response content.
- Full content logging requires an explicit per-job opt-in.

Run `usai-harness audit` to verify your project's gitignore covers
sensitive files and that no keys have been accidentally committed.

## Examples

Three runnable scripts in `docs/examples/` cover the common patterns: a one-call quickstart, a small batch with per-task inspection, and a programmatic audit. Run `usai-harness init` first so a key is configured, then run any of the scripts directly. See `docs/examples/README.md` for what each one demonstrates and what to expect.

## Is this project officially endorsed?

No. See [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT. See [LICENSE](LICENSE).
