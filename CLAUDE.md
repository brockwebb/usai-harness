# CLAUDE.md — usai-harness

## What this is
A pip-installable Python client library for rate-limited, model-agnostic LLM
calls against USAi. See README.md for usage.

## Project conventions
- **Python >=3.12**, dev target 3.14
- **Three dependencies:** httpx, python-dotenv, pyyaml. That's it.
- **Package name:** `usai_harness` (underscore). Pip name: `usai-harness` (hyphen).
- **No dashboards, no real-time UIs.** This is a batch pipeline client library.
- **Fail fast and loud.** Bad keys, bad configs, invalid params: caught at init, not at call 847.
- **Silent failures are bugs.** Every API call outcome is logged. No swallowed exceptions.
- **Append-only cost ledger.** `cost_ledger.jsonl` is never deleted or truncated.
- **Single .env for key management.** All projects point here.

## File locations
- Secrets: `.env` (gitignored), `.usai_key_meta.json` (gitignored)
- Cost data: `cost_ledger.jsonl` (gitignored)
- Model configs: `configs/models.yaml`
- Logs: `logs/` (gitignored)
- Task files: `cc_tasks/` (gitignored)
- Handoffs: `handoffs/` (gitignored)

## Writing conventions
- No two-sentence paragraphs
- No em-dashes
- Italics not bold for emphasis in docs
- Direct prose, no bloat

## Testing
- `pytest` with `pytest-asyncio`
- Tests live in `tests/`
- Every component gets its own test file

## Key technical details
- Rate limit: 2.8 tokens/sec refill, burst 3 (safety margin on USAi's 3/sec hard limit)
- Worker pool: 3 async workers (default)
- Key expiry: 7 days from issued_at
- Key issued_at default: now() - 4 hours (manual key process buffer)
- Cost rates: zeros for now (free credits), update when billing activates
- Transport layer: pluggable via `transport.py`. Default: `httpx` (zero LLM framework deps).
  Optional: LiteLLM (`pip install -e ".[litellm]"`) — plumbed but not yet implemented.
- `client.py` is the integration point. All other modules are independent.
