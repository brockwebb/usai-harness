# Ranked enhancements

## 1. Docs and spec alignment

The highest-value change is synchronizing README, SRS, RTM, API reference, and ops guide with current code.

Specific drift appears around project config fields, family-catalog parameter validation, progress defaults, and checkpoint wording.

Acceptance target:

- `usai_harness.yaml` examples contain only schema-valid fields.
- Parameter validation is described as family-catalog validation at config load plus provider authority at call time.
- `batch(progress=...)` docs match the current default of `text_progress`.
- Checkpoint/resume docs distinguish existing auth recovery from any future durable checkpoint feature.

## 2. `verify-model` and `verify-pool`

Add an empirical verification command that records what a live endpoint accepts for each model.

This fits the existing TEVV posture and the ADR-014 family catalog gap.

Acceptance target:

- `usai-harness verify-model MODEL --params temperature,top_p,max_tokens`
- `usai-harness verify-pool --config usai_harness.yaml`
- Markdown and JSON output artifacts under `tevv/model_checks/`
- No new hard dependencies.

## 3. Local OpenAI-compatible fault mock

Add a dev-only mock endpoint for reliability and performance evidence without needing live USAi access.

This closes planned RTM rows for 429, 5xx, auth halt, malformed responses, and worker throughput.

Acceptance target:

- Mock supports `/models` and `/chat/completions`.
- Configurable status sequence and latency.
- Used only in tests or manual TEVV.
- No package runtime dependency.

## 4. Central redacting logging filter

Add a logging filter that runs `redact_secrets()` over every log record produced by harness loggers.

This reduces missed scrub-call risk when future code paths log exceptions.

Acceptance target:

- Filter attached to `usai_harness` logger during client init or package setup.
- Existing explicit redaction stays in place at sensitive boundaries.
- Tests prove raw API keys are scrubbed from log messages and args.

## 5. Scriptable provider setup

Add non-interactive paths for provider registration in controlled environments.

This is useful for CI, containers, hardened workstations, and scripted onboarding.

Acceptance target:

- `add-provider NAME --base-url URL --api-key-env VAR --non-interactive`
- Optional `--skip-key-prompt` for env-var managed deployments.
- Never accept a raw key through a command-line flag.
- Clear exit codes for missing fields.

## 6. Optional LiteLLM transport

Implement the stub only as an optional transport.

This should stay secondary to the direct `httpx` path because the direct path is the government-environment compatibility story.

Acceptance target:

- `pip install "usai-harness[litellm]"` enables `transport: litellm`.
- Import and version checks fail loud.
- Response shape normalizes into the existing `BatchResult` and logger paths.
- No new hard dependencies.
