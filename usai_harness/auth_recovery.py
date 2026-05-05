"""Stale-credential recovery and manual key rotation (ADR-016).

Two paths share one underlying primitive (upsert into the user-level `.env`):

- `recover_stale_credential` is invoked from `USAiClient.batch()` and
  `USAiClient.complete()` when the endpoint returns 401/403 mid-workload.
  It prompts the user (interactively only — non-TTY contexts get None and
  the caller re-raises the original `AuthHaltError`) and persists the new
  key. The function never logs or echoes the key.

- `handle_set_key` is the CLI subcommand entry point for proactive
  rotation. It validates the named provider against the user-level
  catalog, prompts for a new key, persists it, and optionally tests the
  new key against the provider's `/models` endpoint.

Both helpers take their external interactions as injectable callables so
tests can run without stdin, without writing to the real config dir, and
without spying on real network or filesystem state.
"""

import sys
from pathlib import Path
from typing import Callable, Optional

import httpx

from usai_harness.setup_commands import (
    _fetch_models,
    _load_user_catalog,
    _masked_input,
    _write_env_var,
    user_config_models_path,
)
from usai_harness.key_manager import user_config_env_path


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def recover_stale_credential(
    provider: str,
    api_key_env: str,
    *,
    prompt_fn: Callable[[str], str] = _masked_input,
    env_path_fn: Callable[[], Path] = user_config_env_path,
    write_env_fn: Callable[[Path, str, str], None] = _write_env_var,
    is_interactive: Callable[[], bool] = _stdin_is_tty,
) -> Optional[str]:
    """Interactive credential rotation on auth halt.

    Returns the new key on success, or None if the caller should re-raise
    the original `AuthHaltError`. The None outcomes are: stdin is not
    interactive (CI/non-TTY), the user pressed Ctrl-C, or the user
    submitted an empty line.

    The new key is persisted to the user-level `.env` at the path returned
    by `env_path_fn()`, under the variable name `api_key_env`. The function
    does not touch any in-process credential cache because `DotEnvProvider`
    re-reads per call; the caller refreshes its cached api_key by calling
    `get_key()` again after a successful return.
    """
    if not is_interactive():
        return None

    print(
        f"\nEndpoint returned an authentication error for provider "
        f"'{provider}'. The current credential is rejected.",
        file=sys.stderr,
    )
    try:
        new_key = prompt_fn(
            f"Paste a fresh API key for {provider} (masked while typing): "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print(file=sys.stderr)
        return None
    if not new_key:
        return None

    env_path = env_path_fn()
    write_env_fn(env_path, api_key_env, new_key)
    print("New key saved.", file=sys.stderr)
    return new_key


def handle_set_key(
    provider: str = "usai",
    *,
    prompt_fn: Callable[[str], str] = _masked_input,
    env_path_fn: Callable[[], Path] = user_config_env_path,
    catalog_path_fn: Callable[[], Path] = user_config_models_path,
    write_env_fn: Callable[[Path, str, str], None] = _write_env_var,
    fetch_models_fn: Callable[[str, str], list[str]] = _fetch_models,
) -> int:
    """Manual credential rotation. CLI exit code semantics:

    - 0: key saved (the optional connectivity test may have failed; the
      key is still on disk and the warning is printed to stderr).
    - 1: provider unknown, no key entered, or another precondition failed.

    The new key is persisted under the named provider's `api_key_env`
    variable in the user-level `.env`. The catalog is not modified.
    """
    catalog = _load_user_catalog(catalog_path_fn())
    providers = catalog.get("providers", {}) if isinstance(catalog, dict) else {}
    if provider not in providers:
        print(
            f"Unknown provider '{provider}'. The user-level catalog has: "
            f"{sorted(providers)}. Run 'usai-harness add-provider {provider}' "
            f"first to register it.",
            file=sys.stderr,
        )
        return 1

    spec = providers[provider]
    if not isinstance(spec, dict):
        print(
            f"Catalog entry for provider '{provider}' is malformed.",
            file=sys.stderr,
        )
        return 1

    api_key_env = spec.get("api_key_env")
    if not api_key_env:
        print(
            f"Provider '{provider}' has no `api_key_env` in the user-level "
            f"catalog. `set-key` is for DotEnv-backed providers; for an "
            f"Azure Key Vault provider, rotate the secret in the vault "
            f"directly.",
            file=sys.stderr,
        )
        return 1

    base_url = spec.get("base_url")

    try:
        new_key = prompt_fn(
            f"API key for {provider} (masked while typing): "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print(file=sys.stderr)
        return 1
    if not new_key:
        print("No key entered; nothing saved.", file=sys.stderr)
        return 1

    write_env_fn(env_path_fn(), api_key_env, new_key)
    print(f"New key saved for {provider}.")

    if base_url:
        try:
            models = fetch_models_fn(base_url, new_key)
            print(f"OK: catalog has {len(models)} models.")
        except httpx.HTTPError as e:
            print(
                f"WARNING: connectivity test against {base_url} failed: {e}. "
                f"The key is saved; re-run 'usai-harness verify' once the "
                f"endpoint is reachable.",
                file=sys.stderr,
            )

    return 0
