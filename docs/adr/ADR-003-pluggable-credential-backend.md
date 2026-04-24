# ADR-003: Pluggable Credential Backend

**Status:** Accepted
**Date:** 2026-04-24

## Context

Credentials live in different places across environments. A researcher on a laptop uses a `.env` file. A researcher inside an agency boundary may have Azure Key Vault available. Other environments may require HashiCorp Vault, AWS Secrets Manager, or an agency-specific secret store.

The harness is shared across these environments. Hard-coding one credential source would force every project to work around the default or fork the library.

Projects also run against multiple providers. A single project might call USAi in production and OpenRouter during development. Each provider reads its own key, and the harness needs a clean way to map provider to credential.

## Decision

Define a `CredentialProvider` protocol in `key_manager.py`. The protocol exposes one method:

```python
get_key(provider: str) -> str
```

Ship the following implementations:

1. `DotEnvProvider` — reads from `.env`. Default backend.
2. `EnvVarProvider` — reads from OS environment variables. No file required.
3. `AzureKeyVaultProvider` — reads from Azure Key Vault. Optional backend, installed via `pip install -e ".[azure]"`.

Project configuration selects which backend is active. The model configuration at `configs/models.yaml` specifies `api_key_env` per provider, so different services read different keys from the same credential source.

Example project config:

```yaml
credentials:
  backend: azure_keyvault
  vault_url: https://my-vault.vault.azure.net
```

Example model config fragment:

```yaml
providers:
  usai:
    base_url: https://usai.example.gov/v1
    api_key_env: USAI_API_KEY
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
```

## Consequences

Researchers select the appropriate credential source per project without code changes. The same harness binary serves laptop development and agency-boundary deployment.

Azure dependencies are optional. Environments that do not need Azure do not pay the install cost. The same pattern applies to future backends.

The protocol has one method, which keeps the cost of adding a backend low. Combined with ADR-002, credential backends do not implement freshness or expiry logic. Each returns the current credential and lets the endpoint report failures.

Projects calling multiple providers get clean key isolation. `USAI_API_KEY` and `OPENROUTER_API_KEY` do not collide, and no code changes are needed to support additional providers beyond a config entry.
