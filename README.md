# usai-harness

A pip-installable Python client library for making rate-limited, model-agnostic
LLM calls against USAi. Generalizes API management patterns (provider-agnostic
dispatch, checkpointing, retry with backoff, config-driven model selection)
into a reusable library.

Not a framework. Not a platform. A client library with proper engineering.

## Install

```bash
# From the repo root (editable install)
pip install -e .

# With dev dependencies
pip install -e ".[dev]"

# With optional LiteLLM transport (see Transport Architecture below)
pip install -e ".[litellm]"
```

## Usage

### Single call

```python
from usai_harness import USAiClient

async with USAiClient(project="my-project") as client:
    response = await client.complete(
        messages=[{"role": "user", "content": "Hello"}],
    )
```

### Batch processing

```python
async with USAiClient(project="my-project") as client:
    tasks = [
        {
            "messages": [{"role": "user", "content": f"Question {i}"}],
            "task_id": f"q_{i:04d}",
        }
        for i in range(100)
    ]
    results = await client.batch(tasks, job_name="my-batch-job")
```

Each task dict must contain `messages`. Optional per-task fields: `model`,
`temperature`, `max_tokens`, `system_prompt`, `task_id`, `metadata`. Any other
keys pass through to the transport as provider-specific parameters.

## Transport Architecture

The harness uses a pluggable transport layer. The default transport (`httpx`)
makes direct HTTP calls to any OpenAI-compatible endpoint with zero external
LLM framework dependencies.

### Why not LiteLLM?

LiteLLM (MIT license, by BerriAI) would have been the natural first choice for
multi-provider LLM abstraction. We evaluated it and found the engineering to be
sound. The sole reason for not adopting it as a hard dependency: there is no
guarantee that LiteLLM (or any specific version of it) would be available for
install across the many separate security boundaries that do not share a common
accreditation process. Federal agency environments, air-gapped networks, and
locked-down package repositories each impose their own constraints.

The harness was designed with LiteLLM in mind. The transport abstraction layer
exists so that LiteLLM can be dropped in as an optional backend without changing
any other component. When your environment permits it:

```bash
pip install -e ".[litellm]"
```

The default httpx transport has zero external LLM framework dependencies and
works anywhere Python and an OpenAI-compatible endpoint are available.

## Post-run reports

```bash
usai-harness cost-report
```

## Disclaimer

*This project is not an official product of any federal agency.* See
[DISCLAIMER.md](DISCLAIMER.md) for full text.

## License

MIT
