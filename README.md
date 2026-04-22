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
```

## Usage

```python
from usai_harness import USAiClient

client = USAiClient(project="my-project")
response = await client.complete(
    model="llama-4-maverick",
    messages=[{"role": "user", "content": "Hello"}],
)
```

## Post-run reports

```bash
usai-harness cost-report
```

## Disclaimer

**This project is not an official product of any federal agency.** See
[DISCLAIMER.md](DISCLAIMER.md) for full text.

## License

MIT
