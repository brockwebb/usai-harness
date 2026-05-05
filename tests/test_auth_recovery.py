"""Tests for stale-credential auto-recovery and the manual `set-key` command (ADR-016)."""

import textwrap
from pathlib import Path
from typing import Iterator

import httpx
import pytest

from usai_harness import auth_recovery
from usai_harness.auth_recovery import handle_set_key, recover_stale_credential
from usai_harness.client import USAiClient
from usai_harness.transport import BaseTransport
from usai_harness.worker_pool import AuthHaltError


# ---------- shared fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path_factory):
    for var in ("USAI_API_KEY", "USAI_BASE_URL", "OPENROUTER_API_KEY",
                "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path_factory.mktemp("empty_user_config")
    monkeypatch.setattr(
        "usai_harness.key_manager.user_config_env_path",
        lambda: empty / "usai-harness" / ".env",
    )


@pytest.fixture
def env_path(tmp_path):
    p = tmp_path / ".env"
    p.write_text("USAI_API_KEY=test-key-AAAAAAAA\n")
    return p


def _scripted_inputs(*answers: str):
    iterator: Iterator[str] = iter(answers)

    def _fn(_prompt: str) -> str:
        return next(iterator)

    return _fn


# ---------- recover_stale_credential (path A unit-level) -------------------


def test_recover_returns_none_when_not_interactive(tmp_path):
    written: list = []

    def writer(path, var, val):
        written.append((path, var, val))

    new_key = recover_stale_credential(
        provider="usai",
        api_key_env="USAI_API_KEY",
        prompt_fn=_scripted_inputs("never-called"),
        env_path_fn=lambda: tmp_path / ".env",
        write_env_fn=writer,
        is_interactive=lambda: False,
    )
    assert new_key is None
    assert written == []


def test_recover_returns_none_on_empty_input(tmp_path):
    written: list = []
    new_key = recover_stale_credential(
        provider="usai",
        api_key_env="USAI_API_KEY",
        prompt_fn=_scripted_inputs(""),
        env_path_fn=lambda: tmp_path / ".env",
        write_env_fn=lambda p, v, k: written.append((p, v, k)),
        is_interactive=lambda: True,
    )
    assert new_key is None
    assert written == []


def test_recover_returns_none_on_keyboard_interrupt(tmp_path):
    written: list = []

    def raising_prompt(_prompt: str) -> str:
        raise KeyboardInterrupt

    new_key = recover_stale_credential(
        provider="usai",
        api_key_env="USAI_API_KEY",
        prompt_fn=raising_prompt,
        env_path_fn=lambda: tmp_path / ".env",
        write_env_fn=lambda p, v, k: written.append((p, v, k)),
        is_interactive=lambda: True,
    )
    assert new_key is None
    assert written == []


def test_recover_writes_key_to_disk(tmp_path):
    written: list = []
    target_env = tmp_path / "user.env"
    new_key = recover_stale_credential(
        provider="usai",
        api_key_env="USAI_API_KEY",
        prompt_fn=_scripted_inputs("fresh-key-XYZ"),
        env_path_fn=lambda: target_env,
        write_env_fn=lambda p, v, k: written.append((p, v, k)),
        is_interactive=lambda: True,
    )
    assert new_key == "fresh-key-XYZ"
    assert written == [(target_env, "USAI_API_KEY", "fresh-key-XYZ")]


def test_dotenv_provider_re_reads_after_rotation(tmp_path):
    """Confirm the contract recover_stale_credential relies on: writing to
    the .env on disk and calling DotEnvProvider.get_key() returns the new
    value without any in-process cache invalidation."""
    from usai_harness.key_manager import DotEnvProvider
    from usai_harness.setup_commands import _write_env_var

    user_env = tmp_path / "user.env"
    user_env.write_text("USAI_API_KEY=old-key\n")

    provider = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=tmp_path / "missing-project.env",
        user_env=user_env,
    )
    assert provider.get_key("usai") == "old-key"

    _write_env_var(user_env, "USAI_API_KEY", "rotated-key")
    assert provider.get_key("usai") == "rotated-key"


# ---------- handle_set_key (path B) ----------------------------------------


def _catalog_with(tmp_path: Path, providers: dict) -> Path:
    catalog = tmp_path / "user-models.yaml"
    import yaml
    catalog.write_text(yaml.safe_dump({"providers": providers}))
    return catalog


def test_set_key_happy_path(tmp_path, capsys):
    env = tmp_path / "user.env"
    env.write_text("USAI_API_KEY=old\n")
    catalog = _catalog_with(tmp_path, {
        "usai": {
            "base_url": "https://usai.example/v1",
            "api_key_env": "USAI_API_KEY",
            "models": ["m1", "m2"],
        },
    })
    fetch_calls: list = []
    rc = handle_set_key(
        provider="usai",
        prompt_fn=_scripted_inputs("brand-new-key"),
        env_path_fn=lambda: env,
        catalog_path_fn=lambda: catalog,
        write_env_fn=__import__(
            "usai_harness.setup_commands", fromlist=["_write_env_var"],
        )._write_env_var,
        fetch_models_fn=lambda url, key: fetch_calls.append((url, key)) or ["a", "b", "c"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "saved" in out.lower()
    assert "3 models" in out
    assert "brand-new-key" not in out
    # Key was upserted on disk.
    assert "USAI_API_KEY=brand-new-key" in env.read_text()
    assert fetch_calls == [("https://usai.example/v1", "brand-new-key")]


def test_set_key_default_provider_is_usai(tmp_path):
    env = tmp_path / "user.env"
    catalog = _catalog_with(tmp_path, {
        "usai": {
            "base_url": "https://usai.example/v1",
            "api_key_env": "USAI_API_KEY",
        },
    })
    rc = handle_set_key(
        prompt_fn=_scripted_inputs("k"),
        env_path_fn=lambda: env,
        catalog_path_fn=lambda: catalog,
        fetch_models_fn=lambda *a: [],
    )
    assert rc == 0
    assert "USAI_API_KEY=k" in env.read_text()


def test_set_key_unknown_provider_returns_1(tmp_path, capsys):
    env = tmp_path / "user.env"
    catalog = _catalog_with(tmp_path, {
        "usai": {"base_url": "x", "api_key_env": "USAI_API_KEY"},
    })
    rc = handle_set_key(
        provider="bogus",
        prompt_fn=_scripted_inputs("never-asked"),
        env_path_fn=lambda: env,
        catalog_path_fn=lambda: catalog,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "bogus" in err
    assert "add-provider" in err
    assert not env.exists()


def test_set_key_empty_input_returns_1(tmp_path, capsys):
    env = tmp_path / "user.env"
    catalog = _catalog_with(tmp_path, {
        "usai": {"base_url": "x", "api_key_env": "USAI_API_KEY"},
    })
    rc = handle_set_key(
        provider="usai",
        prompt_fn=_scripted_inputs(""),
        env_path_fn=lambda: env,
        catalog_path_fn=lambda: catalog,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "no key" in err.lower()
    assert not env.exists()


def test_set_key_test_failure_still_saves_with_warning(tmp_path, capsys):
    env = tmp_path / "user.env"
    catalog = _catalog_with(tmp_path, {
        "usai": {
            "base_url": "https://unreachable.example",
            "api_key_env": "USAI_API_KEY",
        },
    })

    def failing_fetch(*_args, **_kwargs):
        raise httpx.ConnectError("cannot reach host")

    rc = handle_set_key(
        provider="usai",
        prompt_fn=_scripted_inputs("saved-anyway"),
        env_path_fn=lambda: env,
        catalog_path_fn=lambda: catalog,
        fetch_models_fn=failing_fetch,
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "saved" in captured.out.lower()
    assert "WARNING" in captured.err
    assert "USAI_API_KEY=saved-anyway" in env.read_text()


def test_set_key_provider_without_api_key_env_fails(tmp_path, capsys):
    env = tmp_path / "user.env"
    catalog = _catalog_with(tmp_path, {
        "usai": {"base_url": "x"},  # api_key_env missing — Azure-style entry
    })
    rc = handle_set_key(
        provider="usai",
        prompt_fn=_scripted_inputs("never"),
        env_path_fn=lambda: env,
        catalog_path_fn=lambda: catalog,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "api_key_env" in err
    assert "Azure" in err or "vault" in err.lower()


# ---------- USAiClient end-to-end recovery (path A integration) ------------


class _AuthFlipTransport(BaseTransport):
    """Returns 401 once on a target task_id, then 200 forever."""

    def __init__(self, fail_task_id: str):
        self.fail_task_id = fail_task_id
        self._failed_once = False
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages,
                   temperature=0.0, max_tokens=4096, system_prompt=None, **kwargs):
        self.calls.append({"api_key": api_key, "model": model})
        if not self._failed_once:
            self._failed_once = True
            return ({}, 401)
        body = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            "model": model,
        }
        return (body, 200)

    async def close(self):
        self.closed = True


class _AlwaysFailTransport(BaseTransport):
    def __init__(self):
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        return ({}, 401)

    async def close(self):
        self.closed = True


def _client(tmp_path, env_path, transport, monkeypatch, *, recovery_key=None):
    """Build a USAiClient with auth_recovery monkeypatched to either
    inject a fresh key or refuse (None)."""
    user_env = tmp_path / "user.env"
    user_env.write_text("")
    monkeypatch.setattr(
        "usai_harness.key_manager.user_config_env_path",
        lambda: user_env,
    )
    if recovery_key is None:
        monkeypatch.setattr(
            "usai_harness.client.recover_stale_credential",
            lambda **kw: None,
        )
    else:
        keys = list(recovery_key) if isinstance(recovery_key, (list, tuple)) \
            else [recovery_key]
        iterator = iter(keys)

        def _recovery(**kw):
            try:
                return next(iterator)
            except StopIteration:
                return None

        monkeypatch.setattr(
            "usai_harness.client.recover_stale_credential",
            _recovery,
        )

    return USAiClient(
        project="auth-test",
        env_path=env_path,
        transport=transport,
        log_dir=tmp_path / "logs",
        ledger_path=tmp_path / "ledger.jsonl",
    )


@pytest.mark.asyncio
async def test_complete_recovers_on_401_and_retries_once(
    tmp_path, env_path, monkeypatch,
):
    transport = _AuthFlipTransport(fail_task_id="ignored")
    client = _client(
        tmp_path, env_path, transport, monkeypatch,
        recovery_key="rotated-key",
    )
    try:
        body = await client.complete(
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await client.close()

    assert body.get("choices")
    # Two transport calls (the 401, then the successful retry).
    assert len(transport.calls) == 2
    # Second call used the rotated key.
    assert transport.calls[1]["api_key"] == "rotated-key"


@pytest.mark.asyncio
async def test_complete_does_not_retry_when_recovery_returns_none(
    tmp_path, env_path, monkeypatch,
):
    transport = _AuthFlipTransport(fail_task_id="ignored")
    client = _client(tmp_path, env_path, transport, monkeypatch, recovery_key=None)
    try:
        body = await client.complete(
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await client.close()

    # Only the 401 call happened; no retry.
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_complete_does_not_loop_recovery_on_repeated_401(
    tmp_path, env_path, monkeypatch,
):
    """Even if recovery returns a new key, a second 401 must not trigger
    a second prompt. The client surfaces the failure."""
    transport = _AlwaysFailTransport()
    client = _client(
        tmp_path, env_path, transport, monkeypatch,
        recovery_key=["first-recovery", "second-recovery"],
    )
    try:
        await client.complete(
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await client.close()

    # Two transport calls: original 401 + one retry. No third call.
    assert len(transport.calls) == 2


class _BatchAuthTransport(BaseTransport):
    """Returns 401 on the Nth call, then 200 forever."""

    def __init__(self, fail_after: int):
        self.fail_after = fail_after
        self._count = 0
        self._failed_once = False
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages,
                   temperature=0.0, max_tokens=4096, system_prompt=None, **kwargs):
        self._count += 1
        self.calls.append({"api_key": api_key, "model": model})
        if self._count == self.fail_after and not self._failed_once:
            self._failed_once = True
            return ({}, 401)
        body = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            "model": model,
        }
        return (body, 200)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_batch_recovers_and_retries_remaining_tasks(
    tmp_path, env_path, monkeypatch, capsys,
):
    transport = _BatchAuthTransport(fail_after=2)
    client = _client(
        tmp_path, env_path, transport, monkeypatch,
        recovery_key="rotated-key",
    )
    tasks = [
        {"task_id": f"t{i}", "messages": [{"role": "user", "content": str(i)}]}
        for i in range(5)
    ]
    try:
        results = await client.batch(tasks, job_name="recovery")
    finally:
        await client.close()
    capsys.readouterr()

    task_ids = sorted(r.task_id for r in results)
    assert task_ids == sorted({r.task_id for r in results})  # no duplicates
    assert len(results) == 5
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_batch_re_raises_when_recovery_unavailable(
    tmp_path, env_path, monkeypatch, capsys,
):
    transport = _BatchAuthTransport(fail_after=1)
    client = _client(tmp_path, env_path, transport, monkeypatch, recovery_key=None)
    tasks = [
        {"task_id": f"t{i}", "messages": [{"role": "user", "content": str(i)}]}
        for i in range(3)
    ]
    try:
        with pytest.raises(AuthHaltError):
            await client.batch(tasks, job_name="halt")
    finally:
        await client.close()
    capsys.readouterr()
