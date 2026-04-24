# CLAUDE.md — usai-harness

## What this is
A pip-installable Python client library for rate-limited, model-agnostic LLM
calls against OpenAI-compatible endpoints. Built for USAi, works anywhere.
See README.md for usage.

## Project conventions
- **Python >=3.12**, dev target 3.14
- **Three hard dependencies:** httpx, python-dotenv, pyyaml. That's it. Optional extras for LiteLLM and Azure Key Vault.
- **Package name:** `usai_harness` (underscore). Pip name: `usai-harness` (hyphen).
- **No dashboards, no real-time UIs.** This is a batch pipeline client library.
- **Fail fast and loud.** Bad configs, invalid params: caught at init, not at call 847.
- **Silent failures are bugs.** Every API call outcome is logged. No swallowed exceptions.
- **Append-only cost ledger.** `cost_ledger.jsonl` is never deleted or truncated. Metadata only, never content.
- **User-level credential storage.** Keys live in a per-user config directory so one rotation covers every project on the machine. Project-local `.env` is an override, not the default.
- **Reactive auth.** No key-expiry metadata files. 401/403 from the endpoint halts the pool cleanly.

## File locations

### In the repository
- Model and provider config: `configs/models.yaml` (presentation overrides only, endpoint is authoritative)
- Source: `usai_harness/`
- Tests: `tests/`
- Documentation: `docs/` (ADRs, SRS, NFR, Architecture, TEVV, RTM, API reference, Ops guide)
- Task files: `cc_tasks/` (gitignored)
- Handoffs: `handoffs/` (gitignored)

### On the user's machine (not in repo)
- User-level credentials and model catalog:
  - Linux/macOS: `~/.config/usai-harness/.env` and `~/.config/usai-harness/models.yaml`
  - Windows: `%APPDATA%\usai-harness\.env` and `%APPDATA%\usai-harness\models.yaml`
- Project-local credentials (optional override): `.env` in project root (gitignored)
- Cost ledger: `cost_ledger.jsonl` in the running project's working directory (gitignored)
- Call logs: `logs/` in the running project's working directory (gitignored)

## Writing conventions
- No two-sentence paragraphs
- No em-dashes
- Italics not bold for emphasis in docs
- Direct prose, no bloat
- Banned word: "clever"

## Testing
- `pytest` with `pytest-asyncio`
- Tests live in `tests/`
- Every component gets its own test file
- Integration tests at `tests/integration/` require a live endpoint and are not run in CI

## Key technical details
- Rate limit default: 2.8 tokens/sec refill, burst 3 (safety margin on USAi's 3/sec hard limit). Per-provider in config.
- Worker pool default: 3 async workers. Per-project in config.
- USAi key lifetime: 7 days. Enforcement is by the endpoint, not by the harness (ADR-002). `usai-harness verify` or `ping` before long jobs as operational practice.
- Cost rates: zero for free-credit periods. Update in `configs/models.yaml`. Ledger entries record the rate applied at call time for retroactive computation.
- Transport layer: pluggable via `transport.py`. Default is `httpx` (zero LLM framework deps). `LiteLLMTransport` is an optional backend via `pip install -e ".[litellm]"`.
- Credential backends: `DotEnvProvider` (default), `EnvVarProvider` (CI/containers), `AzureKeyVaultProvider` (optional via `.[azure]`).
- `client.py` is the integration point. All other modules are independent and testable without it.

## CLI
```
usai-harness init              # first-run setup, writes to user-level config
usai-harness add-provider NAME # register another provider (openrouter, anthropic, etc.)
usai-harness discover-models   # refresh model catalog from endpoints
usai-harness verify            # full health check
usai-harness ping              # quick single-call check
usai-harness cost-report       # ledger aggregation
usai-harness audit             # security hygiene (gitignore, tracked secrets, pip-audit)
```

## Documentation structure
`docs/` contains the systems engineering spine. Read the ADRs first for the design principles, then the SRS for functional requirements, the NFR for quality attributes, the Architecture doc for how components fit, the TEVV plan for how conformance is established, and the RTM for requirement-to-code-to-test traceability.
