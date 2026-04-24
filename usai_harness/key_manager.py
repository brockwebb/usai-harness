"""Credential providers.

Per ADR-003, credential retrieval is pluggable. Per ADR-008, the default backend
looks at project-local .env, then a user-level .env, then the OS environment.
Per ADR-002, expiry is not managed here; a 401/403 from the endpoint halts the
pool (see worker_pool.AuthHaltError).

Exports:
    - CredentialProvider (Protocol)
    - DotEnvProvider (default, layered .env + os.environ)
    - EnvVarProvider (CI/containers, os.environ only)
    - AzureKeyVaultProvider (optional; requires `pip install -e ".[azure]"`)
    - make_credential_provider (factory)
    - user_config_env_path (per-OS user-level .env location)
    - CredentialNotFoundError, CredentialBackendError
"""

import os
import sys
from pathlib import Path
from typing import Optional, Protocol

from dotenv import dotenv_values


class CredentialNotFoundError(Exception):
    """Raised when no credential can be resolved for the requested provider."""


class CredentialBackendError(Exception):
    """Raised when a backend fails to initialize or query its store."""


class CredentialProvider(Protocol):
    """Contract for credential backends. Returns the API key for a named provider.

    Implementations must not cache freshness state. Per ADR-002, the endpoint is
    the source of truth for validity. A provider returns the current value at
    call time; if the underlying store has been updated since the last call,
    the new value is returned on the next call.
    """

    def get_key(self, provider: str) -> str:
        ...


def user_config_env_path() -> Path:
    """Per-OS user-level .env location. No platformdirs dependency (ADR-005, ADR-008)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "usai-harness" / ".env"

    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "usai-harness" / ".env"


class DotEnvProvider:
    """Resolves credentials from .env files with user-level fallback.

    Resolution order per ADR-008 / FR-009a:
        1. Project-local .env (current working directory).
        2. User-level .env (per-OS config directory).
        3. OS environment variable named by the provider's api_key_env.

    The first non-empty match wins. Uses `dotenv_values` so loading a .env
    never mutates `os.environ` as a side effect.
    """

    def __init__(
        self,
        providers: dict[str, str],
        project_env: Optional[Path] = None,
        user_env: Optional[Path] = None,
    ):
        self._providers = dict(providers)
        self._project_env = (
            Path(project_env) if project_env is not None
            else Path.cwd() / ".env"
        )
        self._user_env = (
            Path(user_env) if user_env is not None
            else user_config_env_path()
        )

    def get_key(self, provider: str) -> str:
        if provider not in self._providers:
            raise CredentialNotFoundError(
                f"Provider '{provider}' is not registered with this DotEnvProvider. "
                f"Registered providers: {sorted(self._providers)}."
            )
        env_var = self._providers[provider]

        if self._project_env.exists():
            values = dotenv_values(self._project_env)
            value = (values.get(env_var) or "").strip()
            if value:
                return value

        if self._user_env.exists():
            values = dotenv_values(self._user_env)
            value = (values.get(env_var) or "").strip()
            if value:
                return value

        os_value = os.environ.get(env_var, "").strip()
        if os_value:
            return os_value

        raise CredentialNotFoundError(
            f"No credential for provider '{provider}'. Looked in: "
            f"{self._project_env}, {self._user_env}, and os.environ['{env_var}']. "
            f"Run 'usai-harness init' to configure, or set {env_var} in the "
            f"environment."
        )


class EnvVarProvider:
    """Resolves credentials strictly from os.environ.

    For CI, containers, and orchestrator-managed environments that inject
    secrets as environment variables.
    """

    def __init__(self, providers: dict[str, str]):
        self._providers = dict(providers)

    def get_key(self, provider: str) -> str:
        if provider not in self._providers:
            raise CredentialNotFoundError(
                f"Provider '{provider}' is not registered with this EnvVarProvider. "
                f"Registered providers: {sorted(self._providers)}."
            )
        env_var = self._providers[provider]
        value = os.environ.get(env_var, "").strip()
        if not value:
            raise CredentialNotFoundError(
                f"No credential for provider '{provider}': "
                f"os.environ['{env_var}'] is missing or empty."
            )
        return value


class AzureKeyVaultProvider:
    """Resolves credentials from Azure Key Vault. Optional backend.

    Requires `pip install -e ".[azure]"`. The azure-identity and
    azure-keyvault-secrets packages are not hard dependencies.

    The `providers` mapping associates a provider name with a Key Vault
    secret name, not an environment variable name. The DefaultAzureCredential
    chain is used for auth, so the usual Azure auth methods apply (managed
    identity, CLI, env vars, etc.).
    """

    def __init__(self, providers: dict[str, str], vault_url: str):
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as e:
            raise CredentialBackendError(
                "Azure SDK not installed. Install the 'azure' extra: "
                'pip install -e ".[azure]"'
            ) from e

        self._providers = dict(providers)
        self._vault_url = vault_url
        self._SecretClient = SecretClient
        self._credential = DefaultAzureCredential()
        self._client = SecretClient(vault_url=vault_url, credential=self._credential)

    def get_key(self, provider: str) -> str:
        if provider not in self._providers:
            raise CredentialNotFoundError(
                f"Provider '{provider}' is not registered with this "
                f"AzureKeyVaultProvider. Registered providers: "
                f"{sorted(self._providers)}."
            )
        secret_name = self._providers[provider]
        try:
            secret = self._client.get_secret(secret_name)
        except Exception as e:
            raise CredentialBackendError(
                f"Failed to retrieve secret '{secret_name}' from Azure Key Vault "
                f"at {self._vault_url}: {e}"
            ) from e
        if not secret.value:
            raise CredentialNotFoundError(
                f"Secret '{secret_name}' in Azure Key Vault is empty."
            )
        return secret.value.strip()


def make_credential_provider(
    backend: str,
    providers: dict[str, str],
    **kwargs,
) -> CredentialProvider:
    """Construct the configured credential backend.

    Args:
        backend: one of "dotenv", "env_var", "azure_keyvault".
        providers: mapping of provider name to env var / secret name.
        **kwargs: backend-specific options. For azure_keyvault, 'vault_url' is required.
            DotEnv accepts 'project_env' and 'user_env' path overrides.
    """
    if backend == "dotenv":
        return DotEnvProvider(
            providers=providers,
            project_env=kwargs.get("project_env"),
            user_env=kwargs.get("user_env"),
        )
    if backend == "env_var":
        return EnvVarProvider(providers=providers)
    if backend == "azure_keyvault":
        vault_url = kwargs.get("vault_url")
        if not vault_url:
            raise ValueError(
                "azure_keyvault backend requires 'vault_url' in credentials config."
            )
        return AzureKeyVaultProvider(providers=providers, vault_url=vault_url)
    raise ValueError(
        f"Unknown credential backend: '{backend}'. "
        f"Valid options: 'dotenv', 'env_var', 'azure_keyvault'."
    )
