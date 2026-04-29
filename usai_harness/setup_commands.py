"""Setup and verification CLI subcommands (ADR-009).

Implements: init, add-provider, discover-models, verify, ping. Each handler
takes injectable dependencies so tests can exercise it without hitting real
endpoints or stdin/stdout.
"""

import getpass
import os
import sys
from datetime import datetime, timezone
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


def handle_list_models(
    provider: Optional[str] = None,
    output_format: str = "table",
    models_config_path: Optional[Path] = None,
) -> int:
    """Print the merged model catalog (repo + user-level).

    Read-only. The merged view is what `ProjectConfig` would see at load time.
    Returns 0 if at least one entry remains after filtering, 1 if the catalog
    is empty or the provider filter matches nothing.
    """
    from usai_harness.config import ConfigLoader, ConfigValidationError

    try:
        loader = ConfigLoader(models_config_path=models_config_path)
    except ConfigValidationError as e:
        print(f"Cannot load catalog: {e}", file=sys.stderr)
        return 1

    all_names = loader.list_models()
    if not all_names:
        print(
            "Catalog is empty. Run 'usai-harness init' (first-run) or "
            "'usai-harness discover-models' to populate it.",
            file=sys.stderr,
        )
        return 1

    entries: list[tuple[str, str]] = []
    for name in sorted(all_names):
        m = loader.get_model(name)
        entries.append((name, m.provider))

    if provider is not None:
        filtered = [e for e in entries if e[1] == provider]
        if not filtered:
            available = sorted({e[1] for e in entries})
            print(
                f"No models found for provider '{provider}'. "
                f"Available providers: {available}.",
                file=sys.stderr,
            )
            return 1
        entries = filtered

    if output_format == "names":
        for name, _ in entries:
            print(name)
    elif output_format == "yaml":
        grouped: dict[str, list[str]] = {}
        for name, prov in entries:
            grouped.setdefault(prov, []).append(name)
        out = {
            "providers": {
                prov: {"models": models} for prov, models in grouped.items()
            }
        }
        print(yaml.safe_dump(out, sort_keys=False), end="")
    else:  # table
        name_w = max(len("name"), max(len(e[0]) for e in entries))
        prov_w = max(len("provider"), max(len(e[1]) for e in entries))
        print(f"{'name':<{name_w}}  {'provider':<{prov_w}}")
        print(f"{'-' * name_w}  {'-' * prov_w}")
        for name, prov in entries:
            print(f"{name:<{name_w}}  {prov:<{prov_w}}")

    return 0


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


# ---------- project-init (ADR-013, FR-053..058, IR-006) -----------------

_TEVV_PROMPT = "Reply with the word OK."
_TEVV_EXPECTED_TOKEN = "ok"


def _read_template(name: str) -> str:
    """Load a packaged template file from `usai_harness/templates/`."""
    import importlib.resources as _resources

    return (
        _resources.files("usai_harness.templates")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _render_project_template(template_name: str, **subs: str) -> str:
    """Read a template and substitute `{key}` placeholders with the given values."""
    text = _read_template(template_name)
    for key, val in subs.items():
        text = text.replace("{" + key + "}", str(val))
    return text


def _ensure_dir(path: Path) -> bool:
    """Create directory if missing. Return True if it was newly created."""
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    return not existed


def _append_gitignore_lines(
    gitignore_path: Path, lines: list[str],
) -> list[str]:
    """Append lines to .gitignore that are not already present (line-stripped equality)."""
    existing: list[str] = []
    if gitignore_path.exists():
        existing = [
            line.strip()
            for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        ]
    appended: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and stripped not in existing:
            appended.append(raw)
    if appended:
        with gitignore_path.open("a", encoding="utf-8") as f:
            if existing and existing[-1] != "":
                f.write("\n")
            for line in appended:
                f.write(line.rstrip("\n") + "\n")
    return appended


def _create_project_layout(
    root: Path,
    project_name: str,
    provider_name: str,
    default_model_name: str,
) -> list[tuple[str, str]]:
    """Render templates and write files; existing files are left in place.

    Returns a list of (action, path) describing what changed for the caller's
    summary print. Idempotent across repeated runs.
    """
    actions: list[tuple[str, str]] = []

    for sub in ("output", "output/logs", "tevv", "scripts", "inputs", "outputs"):
        target = root / sub
        actions.append(
            ("created dir" if _ensure_dir(target) else "dir exists",
             str(target)),
        )

    cfg_path = root / "usai_harness.yaml"
    if cfg_path.exists():
        actions.append(("config exists, leaving alone", str(cfg_path)))
    else:
        cfg_text = _render_project_template(
            "usai_harness.yaml.template",
            project_name=project_name,
            provider_name=provider_name,
            default_model_name=default_model_name,
        )
        cfg_path.write_text(cfg_text, encoding="utf-8")
        actions.append(("created config", str(cfg_path)))

    script_path = root / "scripts" / "example_batch.py"
    if script_path.exists():
        actions.append(("example exists, leaving alone", str(script_path)))
    else:
        script_path.write_text(
            _render_project_template("example_batch.py.template"),
            encoding="utf-8",
        )
        actions.append(("created example", str(script_path)))

    gitignore_text = _read_template("gitignore_entries.txt")
    gitignore_lines = gitignore_text.splitlines()
    gitignore_path = root / ".gitignore"
    appended = _append_gitignore_lines(gitignore_path, gitignore_lines)
    if appended:
        actions.append(
            (f"appended {len(appended)} gitignore line(s)", str(gitignore_path)),
        )
    else:
        actions.append(
            ("gitignore already covers harness paths", str(gitignore_path)),
        )

    return actions


async def _run_tevv_smoke_test(
    project_root: Path,
    project_name: str,
    default_model,
    transport=None,
) -> dict:
    """One round-trip via batch() against the project's default model."""
    from usai_harness.client import USAiClient

    started_at = datetime.now(timezone.utc)
    error_msg: Optional[str] = None
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    response_sample: str = ""
    log_path: Optional[Path] = None
    ledger_path: Optional[Path] = None

    client_kwargs: dict = {
        "project": project_name,
        "log_dir": project_root / "output" / "logs",
        "ledger_path": project_root / "output" / "cost_ledger.jsonl",
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        client = USAiClient(**client_kwargs)
        try:
            results = await client.batch(
                tasks=[{
                    "messages": [{"role": "user", "content": _TEVV_PROMPT}],
                    "task_id": "tevv_smoke",
                    "max_tokens": 64,
                }],
                job_name="project-init-tevv",
            )
        finally:
            log_path = client._logger.get_log_path()
            ledger_path = client._cost_tracker.ledger_path
            await client.close()

        if results:
            r = results[0]
            status_code = r.status_code
            latency_ms = r.latency_ms
            usage = (r.response or {}).get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            try:
                response_sample = (
                    (r.response or {})
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                ) or ""
                response_sample = response_sample[:200]
            except Exception:
                response_sample = ""
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"

    verdict = "PASS"
    failure_detail: Optional[str] = None
    if error_msg:
        verdict = "FAIL"
        failure_detail = f"smoke-test exception: {error_msg}"
    elif status_code is None or not (200 <= int(status_code) < 300):
        verdict = "FAIL"
        failure_detail = f"non-2xx status from endpoint: {status_code}"
    elif _TEVV_EXPECTED_TOKEN not in response_sample.lower():
        verdict = "FAIL"
        failure_detail = (
            f"response did not contain '{_TEVV_EXPECTED_TOKEN}': "
            f"{response_sample!r}"
        )
    elif log_path is None or not Path(log_path).exists() or Path(log_path).stat().st_size == 0:
        verdict = "FAIL"
        failure_detail = "call log was not written"
    elif ledger_path is None or not Path(ledger_path).exists() or Path(ledger_path).stat().st_size == 0:
        verdict = "FAIL"
        failure_detail = "cost ledger was not written"

    cost = 0.0
    if prompt_tokens is not None and completion_tokens is not None:
        cost = (
            (prompt_tokens / 1000.0) * default_model.cost_per_1k_input_tokens
            + (completion_tokens / 1000.0) * default_model.cost_per_1k_output_tokens
        )

    return {
        "verdict": verdict,
        "started_at": started_at,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "response_sample": response_sample,
        "failure_detail": failure_detail,
        "log_path": str(log_path) if log_path else None,
        "ledger_path": str(ledger_path) if ledger_path else None,
    }


def _write_tevv_report(
    project_root: Path,
    project_name: str,
    default_model,
    pool_names: list[str],
    smoke_result: dict,
) -> Path:
    """Write the markdown TEVV report for this run."""
    import platform as _platform

    from usai_harness import __version__

    started_at = smoke_result["started_at"]
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    report_dir = project_root / "tevv"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"init_report_{timestamp}.md"

    lines: list[str] = []
    lines.append(f"# TEVV Report: {project_name}")
    lines.append(f"**Date (UTC):** {started_at.isoformat()}")
    lines.append(f"**Verdict:** {smoke_result['verdict']}")
    lines.append("")
    lines.append("## Environment")
    lines.append(f"- Harness version: {__version__}")
    lines.append(f"- Python: {_platform.python_version()}")
    lines.append(f"- OS: {_platform.platform()}")
    lines.append(f"- Project root: {project_root}")
    lines.append("")
    lines.append("## Configuration")
    lines.append(f"- Provider: {default_model.provider}")
    lines.append(f"- Default model: {default_model.name}")
    lines.append(f"- Model pool: {pool_names}")
    lines.append("")
    lines.append("## Smoke Test")
    lines.append(f'- Prompt: "{_TEVV_PROMPT}"')
    lines.append(f"- Status: {smoke_result['status_code']}")
    if smoke_result["latency_ms"] is not None:
        lines.append(f"- Latency: {smoke_result['latency_ms']:.0f} ms")
    else:
        lines.append("- Latency: n/a")
    lines.append(f"- Prompt tokens: {smoke_result['prompt_tokens']}")
    lines.append(f"- Completion tokens: {smoke_result['completion_tokens']}")
    lines.append(f"- Cost (USD): {smoke_result['cost']:.6f}")
    lines.append(f'- Response sample: "{smoke_result["response_sample"]}"')
    lines.append("")
    if smoke_result["verdict"] == "PASS":
        lines.append("## Verdict")
        lines.append(
            "PASS — round-trip succeeded, cost ledger updated, call log updated."
        )
    else:
        lines.append("## Failure")
        lines.append(smoke_result.get("failure_detail") or "(no detail)")
    lines.append("")
    lines.append("## Provenance")
    lines.append(f"- Cost ledger entry: {smoke_result['ledger_path']}")
    lines.append(f"- Call log entry: {smoke_result['log_path']}")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def handle_project_init(transport=None) -> int:
    """Bootstrap the current directory as a USAi Harness project (ADR-013).

    Creates the standard layout (`usai_harness.yaml`, `output/`, `tevv/`,
    `scripts/example_batch.py`) and runs a single TEVV smoke round-trip
    against the project's default model. Writes a markdown report to
    `tevv/init_report_<utc_timestamp>.md`. Returns 0 on TEVV pass, 1 on fail.
    """
    import asyncio

    from usai_harness.config import ConfigLoader, ConfigValidationError

    project_root = Path.cwd()
    project_name = project_root.name

    loader = ConfigLoader()
    try:
        default_model = loader.get_default_model()
    except ConfigValidationError as e:
        print(
            f"Cannot bootstrap: no default model resolved from the harness "
            f"catalog. Run 'usai-harness init' first to register a provider. "
            f"({e})",
            file=sys.stderr,
        )
        return 1

    print("USAi Harness project-init")
    print(f"  Project root: {project_root}")
    print(f"  Project name: {project_name}")
    print(
        f"  Default model: {default_model.name} "
        f"(provider {default_model.provider})"
    )
    print()

    actions = _create_project_layout(
        root=project_root,
        project_name=project_name,
        provider_name=default_model.provider,
        default_model_name=default_model.name,
    )
    for action, path in actions:
        print(f"  {action}: {path}")
    print()

    print(f"  Running TEVV smoke test against {default_model.name}...")
    smoke_result = asyncio.run(_run_tevv_smoke_test(
        project_root=project_root,
        project_name=project_name,
        default_model=default_model,
        transport=transport,
    ))

    report_path = _write_tevv_report(
        project_root=project_root,
        project_name=project_name,
        default_model=default_model,
        pool_names=[default_model.name],
        smoke_result=smoke_result,
    )
    print(f"  TEVV report: {report_path}")
    print(f"  Verdict: {smoke_result['verdict']}")
    if smoke_result["verdict"] == "FAIL":
        print(
            f"  Failure: {smoke_result['failure_detail']}",
            file=sys.stderr,
        )

    return 0 if smoke_result["verdict"] == "PASS" else 1
