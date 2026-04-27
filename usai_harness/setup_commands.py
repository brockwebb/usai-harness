"""Setup and verification CLI subcommands (ADR-009).

Implements: init, add-provider, discover-models, verify, ping. Each handler
takes injectable dependencies so tests can exercise it without hitting real
endpoints or stdin/stdout.
"""

import getpass
import os
import sys
from pathlib import Path
from typing import Callable, Optional

import httpx
import yaml

from usai_harness.key_manager import user_config_env_path


def _masked_input(prompt: str) -> str:
    """Read a key from stdin, echoing '*' per character. Cross-platform.

    Replaces `getpass.getpass()` for the credential-prompt case where users
    pasting a long key into a silent prompt routinely think the paste failed.
    The key itself is never written to the terminal; only `*` characters are
    echoed. Backspace is handled. On a non-TTY stdin (CI piped input, tests),
    falls back to a plain line read with no echo.
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()

    if sys.platform == "win32":
        try:
            import msvcrt
        except ImportError:
            return getpass.getpass("")
        buf: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch in ("\b", "\x7f"):
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            buf.append(ch)
            sys.stdout.write("*")
            sys.stdout.flush()
        return "".join(buf)

    try:
        import termios
        import tty
    except ImportError:
        return getpass.getpass("")

    fd = sys.stdin.fileno()
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\r\n")

    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        buf = []
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch in ("\x7f", "\b"):
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            buf.append(ch)
            sys.stdout.write("*")
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
    return "".join(buf)


def _mask_for_echo(value: str, tail: int = 4) -> str:
    """Render a key as `****<last N>` for confirmation lines.

    Short values (<= 2*tail) are fully masked to avoid revealing too much of
    the secret. The tail is intentionally small and matches the convention
    other CLIs use for credential confirmation (AWS, gcloud).
    """
    if not value:
        return ""
    if len(value) <= tail * 2:
        return "*" * len(value)
    return ("*" * (len(value) - tail)) + value[-tail:]


def user_config_models_path() -> Path:
    """Companion to user_config_env_path; where init/discover-models write the catalog."""
    env_path = user_config_env_path()
    return env_path.parent / "models.yaml"


def _ensure_parent_dir(path: Path) -> None:
    """Create the parent directory with 0o700 on Unix if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass


def _write_env_var(env_path: Path, var_name: str, value: str) -> None:
    """Upsert VAR=VALUE into a .env file; 0o600 on Unix.

    Preserves existing lines, updates the named variable if present, appends
    if not.
    """
    _ensure_parent_dir(env_path)
    existing_lines = (
        env_path.read_text().splitlines() if env_path.exists() else []
    )
    updated: list[str] = []
    found = False
    prefix = f"{var_name}="
    for line in existing_lines:
        if line.strip().startswith(prefix):
            updated.append(f"{var_name}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"{var_name}={value}")
    env_path.write_text("\n".join(updated) + "\n")
    if sys.platform != "win32":
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass


def _load_user_catalog(path: Optional[Path] = None) -> dict:
    """Load user-level models.yaml, returning {} if absent or malformed."""
    path = path or user_config_models_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        print(
            f"Warning: user-level catalog at {path} is malformed: {e}",
            file=sys.stderr,
        )
        return {}
    return data if isinstance(data, dict) else {}


def _write_user_catalog(catalog: dict, path: Optional[Path] = None) -> Path:
    """Write the user-level models.yaml, creating the directory if needed."""
    path = path or user_config_models_path()
    _ensure_parent_dir(path)
    path.write_text(yaml.safe_dump(catalog, sort_keys=False))
    return path


def _fetch_models(base_url: str, api_key: str, timeout: float = 30.0) -> list[str]:
    """GET {base_url}/models and return the list of model IDs."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    data = body.get("data", []) if isinstance(body, dict) else []
    return [m["id"] for m in data if isinstance(m, dict) and "id" in m]


def _test_completion(
    base_url: str, api_key: str, model: str, timeout: float = 60.0,
) -> bool:
    """Fire one minimal completion. Return True on 2xx."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
    return 200 <= resp.status_code < 300


def _probe_path_prefix(
    base_url: str,
    api_key: str,
    fetch_fn: Callable[[str, str], list[str]] = _fetch_models,
) -> Optional[tuple[str, list[str]]]:
    """Probe common API path prefixes; return (resolved_url, models) on the first 200.

    Tries `/api/v1` (USAi convention), then `/v1` (OpenAI convention), then
    the bare URL (the user already included a prefix, or the endpoint serves
    `/models` at root). The first call that returns without raising
    `httpx.HTTPError` wins. A 200 with an empty model list still counts as
    success; the probe's job is to identify the correct prefix, not to
    validate the catalog.

    Returns None when every candidate raises, leaving the caller to fall back
    (warn, prompt for a default model, save credentials anyway).
    """
    base_clean = base_url.rstrip("/")
    candidates = (
        base_clean + "/api/v1",
        base_clean + "/v1",
        base_clean,
    )
    for url in candidates:
        try:
            models = fetch_fn(url, api_key)
        except httpx.HTTPError:
            continue
        return url, models
    return None


def handle_init(
    prompt_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = _masked_input,
    env_path: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    fetch_models_fn: Callable[[str, str], list[str]] = _fetch_models,
    test_completion_fn: Callable[[str, str, str], bool] = _test_completion,
) -> int:
    """Interactive first-run setup. Writes to user-level .env and models.yaml.

    Idempotent against re-run (upserts the named env var and the named
    provider entry in the catalog).
    """
    env_path = env_path or user_config_env_path()
    catalog_path = catalog_path or user_config_models_path()

    print("USAi Harness — first-run setup")
    print(f"  User config directory: {env_path.parent}")
    print()

    provider_name = prompt_fn("Provider name [usai]: ").strip() or "usai"
    base_url = prompt_fn(
        f"Base URL for {provider_name} (e.g. https://your-endpoint.example.com): "
    ).strip()
    if not base_url:
        print("Base URL is required.", file=sys.stderr)
        return 2
    api_key_env = f"{provider_name.upper()}_API_KEY"
    api_key = getpass_fn(
        f"API key (stored as {api_key_env}, masked while typing): "
    ).strip()
    if not api_key:
        print("API key is required.", file=sys.stderr)
        return 2

    _write_env_var(env_path, api_key_env, api_key)
    print(f"Key saved: {_mask_for_echo(api_key)}")

    user_input_url = base_url.rstrip("/")
    probe = _probe_path_prefix(user_input_url, api_key, fetch_models_fn)

    discovery_failed = probe is None
    if probe is not None:
        resolved_url, models = probe
        if resolved_url != user_input_url:
            print(f"Detected API at {resolved_url}")
    else:
        resolved_url = user_input_url
        models = []
        print(
            f"Model discovery unavailable from {user_input_url} "
            f"(tried /api/v1, /v1, and bare). Skipping catalog population.",
            file=sys.stderr,
        )

    if not models:
        if not discovery_failed:
            print(
                f"Endpoint reachable at {resolved_url} but /models returned "
                f"no models. Skipping catalog population.",
                file=sys.stderr,
            )
        fallback = prompt_fn(
            "Enter a model ID to use as default (or leave blank to skip): "
        ).strip()
        if fallback:
            models = [fallback]

    catalog = _load_user_catalog(catalog_path)
    catalog.setdefault("providers", {})
    catalog["providers"][provider_name] = {
        "base_url": resolved_url,
        "api_key_env": api_key_env,
        "models": models,
    }
    _write_user_catalog(catalog, catalog_path)

    test_status: Optional[str] = None
    if models and not discovery_failed:
        test_model = models[0]
        ok = test_completion_fn(resolved_url, api_key, test_model)
        if ok:
            test_status = f"Test completion against {test_model} succeeded"
        else:
            test_status = (
                f"Test completion against {test_model} failed; "
                f"credentials saved anyway. Run 'usai-harness verify' to retry."
            )

    print()
    print(f"Credentials written to {env_path}")
    if models:
        print(f"{len(models)} model(s) cached at {catalog_path}")
    else:
        print(
            f"No models cached. Set a default model with 'usai-harness "
            f"discover-models {provider_name}' once the endpoint is reachable, "
            f"or pass --model to ping/complete."
        )
    if test_status is not None:
        print(test_status)
    print()
    print("Run 'usai-harness verify' at any time to re-check.")
    return 0


def handle_add_provider(
    name: str,
    prompt_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = _masked_input,
    env_path: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    fetch_models_fn: Callable[[str, str], list[str]] = _fetch_models,
    test_completion_fn: Callable[[str, str, str], bool] = _test_completion,
) -> int:
    """Register an additional provider alongside existing ones."""
    env_path = env_path or user_config_env_path()
    catalog_path = catalog_path or user_config_models_path()

    name = name.strip()
    if not name:
        print("Provider name is required.", file=sys.stderr)
        return 2

    print(f"USAi Harness — adding provider '{name}'")
    print(f"  User config directory: {env_path.parent}")
    print()

    base_url = prompt_fn(f"Base URL for {name}: ").strip()
    if not base_url:
        print("Base URL is required.", file=sys.stderr)
        return 2
    api_key_env = f"{name.upper()}_API_KEY"
    api_key = getpass_fn(
        f"API key (stored as {api_key_env}, masked while typing): "
    ).strip()
    if not api_key:
        print("API key is required.", file=sys.stderr)
        return 2

    _write_env_var(env_path, api_key_env, api_key)
    print(f"Key saved: {_mask_for_echo(api_key)}")

    try:
        models = fetch_models_fn(base_url, api_key)
    except httpx.HTTPError as e:
        print(f"Failed to reach {base_url}/models: {e}", file=sys.stderr)
        return 3

    catalog = _load_user_catalog(catalog_path)
    catalog.setdefault("providers", {})
    catalog["providers"][name] = {
        "base_url": base_url,
        "api_key_env": api_key_env,
        "models": models,
    }
    _write_user_catalog(catalog, catalog_path)

    if not models:
        print(
            f"Provider reachable but returned no models. "
            f"Check {base_url}/models.",
            file=sys.stderr,
        )
        return 4
    test_model = models[0]
    ok = test_completion_fn(base_url, api_key, test_model)
    if not ok:
        print(
            f"Model list retrieved but test completion against "
            f"{test_model} failed.",
            file=sys.stderr,
        )
        return 5

    print()
    print(f"Provider '{name}' registered.")
    print(f"{len(models)} models cached at {catalog_path}")
    return 0


def handle_discover_models(
    provider: Optional[str] = None,
    catalog_path: Optional[Path] = None,
    fetch_models_fn: Callable[[str, str], list[str]] = _fetch_models,
) -> int:
    """Refresh the live model catalog for one or all providers.

    Does not touch credentials. Does not modify repo-level configs/models.yaml.
    """
    from usai_harness.key_manager import DotEnvProvider

    catalog_path = catalog_path or user_config_models_path()
    catalog = _load_user_catalog(catalog_path)
    providers = catalog.get("providers", {})
    if not providers:
        print(
            "No providers configured. Run 'usai-harness init' first.",
            file=sys.stderr,
        )
        return 1

    if provider is not None and provider not in providers:
        print(f"Unknown provider: {provider!r}", file=sys.stderr)
        return 2

    targets = [provider] if provider else list(providers.keys())
    env_map = {p: providers[p]["api_key_env"] for p in targets}
    credentials = DotEnvProvider(providers=env_map)

    any_failed = False
    for p in targets:
        spec = providers[p]
        try:
            api_key = credentials.get_key(p)
            models = fetch_models_fn(spec["base_url"], api_key)
            spec["models"] = models
            print(f"{p}: {len(models)} models")
        except Exception as e:
            print(f"{p}: {e}", file=sys.stderr)
            any_failed = True

    _write_user_catalog(catalog, catalog_path)
    if any_failed:
        print(
            "discover-models: one or more providers failed; the rest were "
            "refreshed. Re-run when the failing endpoint is reachable.",
            file=sys.stderr,
        )
    return 0


def handle_verify(
    catalog_path: Optional[Path] = None,
    fetch_models_fn: Callable[[str, str], list[str]] = _fetch_models,
    test_completion_fn: Callable[[str, str, str], bool] = _test_completion,
) -> int:
    """End-to-end health check for all configured providers."""
    from usai_harness.key_manager import DotEnvProvider

    catalog_path = catalog_path or user_config_models_path()
    catalog = _load_user_catalog(catalog_path)
    providers = catalog.get("providers", {})
    if not providers:
        print(
            "No providers configured. Run 'usai-harness init' first.",
            file=sys.stderr,
        )
        return 1

    env_map = {p: providers[p]["api_key_env"] for p in providers}
    credentials = DotEnvProvider(providers=env_map)

    print(f"{'Provider':<16} {'Creds':<7} {'Catalog':<10} {'Completion':<12} Status")
    any_failed = False
    for name, spec in providers.items():
        creds_ok = False
        catalog_status = "-"
        completion_status = "-"
        status_msg = "FAIL"

        try:
            api_key = credentials.get_key(name)
            creds_ok = True
        except Exception as e:
            print(
                f"{name:<16} {'x':<7} {'-':<10} {'-':<12} FAIL: {e}"
            )
            any_failed = True
            continue

        try:
            models = fetch_models_fn(spec["base_url"], api_key)
            catalog_status = f"ok ({len(models)})"
        except Exception as e:
            print(
                f"{name:<16} {'ok':<7} {'x':<10} {'-':<12} FAIL: {e}"
            )
            any_failed = True
            continue

        if not models:
            print(
                f"{name:<16} {'ok':<7} {catalog_status:<10} {'-':<12} "
                f"FAIL: no models returned"
            )
            any_failed = True
            continue

        try:
            ok = test_completion_fn(spec["base_url"], api_key, models[0])
            completion_status = "ok" if ok else "x"
            status_msg = "PASS" if ok else "FAIL"
            if not ok:
                any_failed = True
        except Exception as e:
            print(
                f"{name:<16} {'ok':<7} {catalog_status:<10} "
                f"{'x':<12} FAIL: {e}"
            )
            any_failed = True
            continue

        print(
            f"{name:<16} {'ok':<7} {catalog_status:<10} "
            f"{completion_status:<12} {status_msg}"
        )

    return 0 if not any_failed else 1


def handle_ping(model: Optional[str] = None) -> int:
    """Minimal single-call check against the default provider.

    If `model` is None, the harness picks the default model from the
    configured catalog. Pass `model` explicitly when the user-level
    catalog is empty (for example after `init` was run against an
    endpoint whose `/models` was unavailable).
    """
    import asyncio

    from usai_harness.client import USAiClient

    async def _run() -> int:
        client = USAiClient(project="ping")
        try:
            kwargs: dict = {
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            }
            if model:
                kwargs["model"] = model
            resp = await client.complete(**kwargs)
            return 0 if resp and "choices" in resp else 1
        finally:
            await client.close()

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"ping failed: {e}", file=sys.stderr)
        return 1
