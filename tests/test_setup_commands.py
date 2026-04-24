"""Tests for usai_harness.setup_commands (ADR-009)."""

import os
import stat
import sys

import httpx
import pytest
import yaml

from usai_harness import setup_commands


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect user-config paths into tmp_path and strip API-key env vars."""
    for var in ("USAI_API_KEY", "OPENROUTER_API_KEY",
                "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    env_path = tmp_path / "user" / ".env"
    catalog_path = tmp_path / "user" / "models.yaml"
    monkeypatch.setattr(
        "usai_harness.setup_commands.user_config_env_path",
        lambda: env_path,
    )
    monkeypatch.setattr(
        "usai_harness.setup_commands.user_config_models_path",
        lambda: catalog_path,
    )
    # The key_manager version is referenced by DotEnvProvider default user_env.
    monkeypatch.setattr(
        "usai_harness.key_manager.user_config_env_path",
        lambda: env_path,
    )


def _prompt_sequence(*answers):
    answers = iter(answers)

    def prompt(_msg):
        return next(answers)

    return prompt


def _getpass_const(val):
    return lambda _msg: val


# ---------- handle_init ---------------------------------------------------


def test_init_happy_path(tmp_path, monkeypatch, capsys):
    fetched = []

    def fake_fetch(base_url, api_key):
        fetched.append((base_url, api_key))
        return ["m-alpha", "m-beta", "m-gamma"]

    completions = []

    def fake_test(base_url, api_key, model):
        completions.append((base_url, api_key, model))
        return True

    rc = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const("the-secret-key"),
        fetch_models_fn=fake_fetch,
        test_completion_fn=fake_test,
    )
    assert rc == 0
    env_path = setup_commands.user_config_env_path()
    catalog_path = setup_commands.user_config_models_path()

    assert env_path.read_text().strip() == "USAI_API_KEY=the-secret-key"
    catalog = yaml.safe_load(catalog_path.read_text())
    assert "usai" in catalog["providers"]
    assert catalog["providers"]["usai"]["models"] == ["m-alpha", "m-beta", "m-gamma"]
    assert fetched == [("https://example.com/v1", "the-secret-key")]
    assert completions == [("https://example.com/v1", "the-secret-key", "m-alpha")]


def test_init_empty_base_url_returns_2():
    rc = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", ""),
        getpass_fn=_getpass_const("x"),
        fetch_models_fn=lambda *a: [],
        test_completion_fn=lambda *a: True,
    )
    assert rc == 2


def test_init_empty_api_key_returns_2():
    rc = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const(""),
        fetch_models_fn=lambda *a: [],
        test_completion_fn=lambda *a: True,
    )
    assert rc == 2


def test_init_fetch_http_error_returns_3():
    def boom(*a):
        raise httpx.ConnectError("no route")

    rc = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=boom,
        test_completion_fn=lambda *a: True,
    )
    assert rc == 3


def test_init_empty_model_list_returns_4():
    rc = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: [],
        test_completion_fn=lambda *a: True,
    )
    assert rc == 4


def test_init_test_completion_failure_returns_5():
    rc = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: False,
    )
    assert rc == 5


def test_init_idempotent_upsert(tmp_path):
    # First run
    rc1 = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const("first-key"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    assert rc1 == 0

    # Second run with a new key and new model list
    rc2 = setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://example.com/v1"),
        getpass_fn=_getpass_const("second-key"),
        fetch_models_fn=lambda *a: ["m2", "m3"],
        test_completion_fn=lambda *a: True,
    )
    assert rc2 == 0

    env_path = setup_commands.user_config_env_path()
    catalog_path = setup_commands.user_config_models_path()
    env_text = env_path.read_text()
    assert "USAI_API_KEY=second-key" in env_text
    assert "first-key" not in env_text
    catalog = yaml.safe_load(catalog_path.read_text())
    assert catalog["providers"]["usai"]["models"] == ["m2", "m3"]


# ---------- _write_env_var ------------------------------------------------


def test_write_env_var_creates_file(tmp_path):
    env = tmp_path / "sub" / ".env"
    setup_commands._write_env_var(env, "USAI_API_KEY", "v1")

    assert env.read_text().strip() == "USAI_API_KEY=v1"
    if sys.platform != "win32":
        mode = stat.S_IMODE(env.stat().st_mode)
        assert mode == 0o600


def test_write_env_var_preserves_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nBAZ=qux\n")
    setup_commands._write_env_var(env, "USAI_API_KEY", "new")
    lines = env.read_text().splitlines()
    assert "FOO=bar" in lines
    assert "BAZ=qux" in lines
    assert "USAI_API_KEY=new" in lines


def test_write_env_var_updates_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text("USAI_API_KEY=old\nFOO=bar\n")
    setup_commands._write_env_var(env, "USAI_API_KEY", "new")
    lines = env.read_text().splitlines()
    assert "USAI_API_KEY=new" in lines
    assert "USAI_API_KEY=old" not in lines
    assert "FOO=bar" in lines


# ---------- handle_add_provider -------------------------------------------


def test_add_provider_happy_path(tmp_path):
    # First register usai so add-provider alongside makes sense
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://usai.example/v1"),
        getpass_fn=_getpass_const("u-key"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    rc = setup_commands.handle_add_provider(
        "openrouter",
        prompt_fn=_prompt_sequence("https://or.example/v1"),
        getpass_fn=_getpass_const("or-key"),
        fetch_models_fn=lambda *a: ["or-m"],
        test_completion_fn=lambda *a: True,
    )
    assert rc == 0

    catalog = yaml.safe_load(
        setup_commands.user_config_models_path().read_text()
    )
    assert set(catalog["providers"]) == {"usai", "openrouter"}
    env_text = setup_commands.user_config_env_path().read_text()
    assert "USAI_API_KEY=u-key" in env_text
    assert "OPENROUTER_API_KEY=or-key" in env_text


def test_add_provider_does_not_touch_existing(tmp_path):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://usai.example/v1"),
        getpass_fn=_getpass_const("u-key"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    pre = yaml.safe_load(
        setup_commands.user_config_models_path().read_text()
    )["providers"]["usai"]

    setup_commands.handle_add_provider(
        "openrouter",
        prompt_fn=_prompt_sequence("https://or.example/v1"),
        getpass_fn=_getpass_const("or-key"),
        fetch_models_fn=lambda *a: ["or-m"],
        test_completion_fn=lambda *a: True,
    )

    post = yaml.safe_load(
        setup_commands.user_config_models_path().read_text()
    )["providers"]["usai"]
    assert pre == post


def test_add_provider_fetch_failure_returns_3():
    def boom(*a):
        raise httpx.ConnectError("no route")
    rc = setup_commands.handle_add_provider(
        "newone",
        prompt_fn=_prompt_sequence("https://ex.example/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=boom,
        test_completion_fn=lambda *a: True,
    )
    assert rc == 3


# ---------- handle_discover_models ----------------------------------------


def test_discover_models_no_catalog_returns_1():
    rc = setup_commands.handle_discover_models()
    assert rc == 1


def test_discover_models_unknown_provider_returns_2(tmp_path, monkeypatch):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")
    rc = setup_commands.handle_discover_models(
        provider="nonexistent",
        fetch_models_fn=lambda *a: ["m9"],
    )
    assert rc == 2


def test_discover_models_all(tmp_path, monkeypatch):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["old"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")

    rc = setup_commands.handle_discover_models(
        fetch_models_fn=lambda *a: ["new1", "new2"],
    )
    assert rc == 0
    catalog = yaml.safe_load(
        setup_commands.user_config_models_path().read_text()
    )
    assert catalog["providers"]["usai"]["models"] == ["new1", "new2"]


def test_discover_models_single_provider(tmp_path, monkeypatch):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["old"],
        test_completion_fn=lambda *a: True,
    )
    setup_commands.handle_add_provider(
        "openrouter",
        prompt_fn=_prompt_sequence("https://or/v1"),
        getpass_fn=_getpass_const("o"),
        fetch_models_fn=lambda *a: ["or-old"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")

    rc = setup_commands.handle_discover_models(
        provider="usai",
        fetch_models_fn=lambda *a: ["new-usai"],
    )
    assert rc == 0
    catalog = yaml.safe_load(
        setup_commands.user_config_models_path().read_text()
    )
    assert catalog["providers"]["usai"]["models"] == ["new-usai"]
    assert catalog["providers"]["openrouter"]["models"] == ["or-old"]


def test_discover_models_partial_failure_returns_3(tmp_path, monkeypatch):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    setup_commands.handle_add_provider(
        "openrouter",
        prompt_fn=_prompt_sequence("https://or/v1"),
        getpass_fn=_getpass_const("o"),
        fetch_models_fn=lambda *a: ["om"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")

    def mixed(base_url, api_key):
        if "or" in base_url:
            raise httpx.ConnectError("or down")
        return ["ok-model"]

    rc = setup_commands.handle_discover_models(fetch_models_fn=mixed)
    assert rc == 3


# ---------- handle_verify -------------------------------------------------


def test_verify_all_pass(tmp_path, monkeypatch, capsys):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")
    rc = setup_commands.handle_verify(
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out


def test_verify_catalog_failure(tmp_path, monkeypatch):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")

    def boom(*a):
        raise httpx.ConnectError("no route")

    rc = setup_commands.handle_verify(
        fetch_models_fn=boom,
        test_completion_fn=lambda *a: True,
    )
    assert rc != 0


def test_verify_completion_failure(tmp_path, monkeypatch):
    setup_commands.handle_init(
        prompt_fn=_prompt_sequence("usai", "https://ex/v1"),
        getpass_fn=_getpass_const("k"),
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: True,
    )
    monkeypatch.setenv("USAI_API_KEY", "k")

    rc = setup_commands.handle_verify(
        fetch_models_fn=lambda *a: ["m1"],
        test_completion_fn=lambda *a: False,
    )
    assert rc != 0


# ---------- handle_ping ---------------------------------------------------


def test_ping_success(monkeypatch):
    """Mock USAiClient so no real network. Return a 2xx body → exit 0."""
    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def complete(self, **kw):
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                              "total_tokens": 2}}

        async def close(self):
            pass

    monkeypatch.setattr(
        "usai_harness.client.USAiClient",
        FakeClient,
    )
    rc = setup_commands.handle_ping()
    assert rc == 0


def test_ping_failure_returns_1(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "usai_harness.client.USAiClient",
        FakeClient,
    )
    rc = setup_commands.handle_ping()
    err = capsys.readouterr().err
    assert rc == 1
    assert "ping failed" in err


def test_fetch_models_url_composition_preserves_path_prefix(monkeypatch):
    """_fetch_models must compose base_url + '/models' without stripping the prefix."""
    import httpx as _httpx

    captured = {}
    real_client_cls = _httpx.Client

    def handler(request):
        captured["url"] = str(request.url)
        return _httpx.Response(200, json={"data": [{"id": "m1"}]})

    def fake_client(**kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(transport=_httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(setup_commands.httpx, "Client", fake_client)

    setup_commands._fetch_models("https://example.com/api/v1", "K")
    assert captured["url"] == "https://example.com/api/v1/models"

    captured.clear()
    setup_commands._fetch_models("https://example.com/api/v1/", "K")
    assert captured["url"] == "https://example.com/api/v1/models"


def test_no_input_used_for_keys():
    """Structural regression guard: no setup path reads a key via input() (FR-041)."""
    import ast
    import pathlib

    source = pathlib.Path("usai_harness/setup_commands.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name == "input" and node.args and isinstance(node.args[0], ast.Constant):
                prompt = str(node.args[0].value).lower()
                assert "key" not in prompt and "password" not in prompt, (
                    f"input() used with key-shaped prompt: {prompt!r}. "
                    f"Use getpass.getpass() for credentials (FR-041)."
                )
