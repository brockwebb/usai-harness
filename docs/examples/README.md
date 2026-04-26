# Examples

Three runnable scripts that demonstrate the public Python API of `usai-harness` end-to-end. Each script is self-contained; pick whichever matches the pattern you need.

## Prerequisites

Run `usai-harness init` once to configure at least one provider. The init command writes credentials to the user-level config directory and pulls the live model catalog from the endpoint. After that, every script in this directory works without any per-script setup.

If `usai-harness init` is not appropriate for your environment (CI containers, locked-down agency machines), use the `EnvVarProvider` backend by exporting the relevant `*_API_KEY` environment variables. See `docs/api-reference.md` section 4.2 for details.

## 01_quickstart.py

What it demonstrates: a single chat-completion call through `USAiClient.complete()` using the configured default provider. Reads top to bottom in 30 seconds. Useful as a copy-paste seed for any script that needs one model call.

How to run:

```bash
python docs/examples/01_quickstart.py
```

What you should see: a one-sentence response printed to stdout, followed by the model identifier the endpoint actually answered with and the prompt and completion token counts.

## 02_batch.py

What it demonstrates: a small batch of seven prompts processed through the worker pool. Shows the rate-limited, logged, cost-tracked pattern that the harness exists to provide. Demonstrates iterating over `list[TaskResult]` to inspect per-task outcomes alongside the aggregate summary.

How to run:

```bash
python docs/examples/02_batch.py
```

What you should see: the harness's built-in post-run report printed by `client.batch()`, then a custom summary line and a per-task outcome list. Each successful task prints a truncated response; each failed task prints the status code and error message.

If you see HTTP 404 on every task, the configured default model is one that does not support `/chat/completions` on the active provider's OpenAI-compat layer (some Gemini variants behave this way). Pin a known-good model with the `USAI_HARNESS_EXAMPLE_MODEL` environment variable:

```bash
USAI_HARNESS_EXAMPLE_MODEL="models/gemini-2.5-flash" python docs/examples/02_batch.py
```

Note: `client.batch()` currently returns `list[TaskResult]` directly and prints a formatted report to stdout via the internal report module. There is no public `BatchReport` dataclass; aggregate metrics in this example are computed from the result list.

## 03_audit.py

What it demonstrates: programmatic invocation of the same checks `usai-harness audit` runs from the CLI. Suitable for wiring into a pre-commit hook, an internal CI step, or a release script.

How to run:

```bash
python docs/examples/03_audit.py
echo "exit code: $?"
```

What you should see: the audit report (gitignore coverage, tracked-secrets scan, pip-audit invocation), then an exit code of 0 if every check passed or 1 if any finding was reported.

The handler is imported from `usai_harness.audit_command`. It is a stable submodule import; the same handler is not currently re-exported under the top-level `usai_harness` namespace.
