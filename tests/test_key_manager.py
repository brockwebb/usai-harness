"""Tests for credential providers (ADR-003, ADR-008)."""

import sys
from pathlib import Path

import pytest

from usai_harness.key_manager import (
    AzureKeyVaultProvider,
    CredentialBackendError,
    CredentialNotFoundError,
    DotEnvProvider,
    EnvVarProvider,
    make_credential_provider,
    user_config_env_path,
)


def _write_env(path: Path, **vars: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{k}={v}" for k, v in vars.items()) + "\n")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Strip credential env vars and per-OS config pointers so no host state leaks in."""
    for var in ("USAI_API_KEY", "OPENROUTER_API_KEY", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)


# ---------- DotEnvProvider (10) -------------------------------------------


def test_dotenv_project_local_wins(tmp_path):
    project_env = tmp_path / "project.env"
    user_env = tmp_path / "user.env"
    _write_env(project_env, USAI_API_KEY="project-value")
    _write_env(user_env, USAI_API_KEY="user-value")

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=user_env,
    )
    assert p.get_key("usai") == "project-value"


def test_dotenv_user_level_fallback(tmp_path):
    project_env = tmp_path / "missing.env"
    user_env = tmp_path / "user.env"
    _write_env(user_env, USAI_API_KEY="user-value")

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=user_env,
    )
    assert p.get_key("usai") == "user-value"


def test_dotenv_osenv_fallback(tmp_path, monkeypatch):
    project_env = tmp_path / "missing.env"
    user_env = tmp_path / "missing_user.env"
    monkeypatch.setenv("USAI_API_KEY", "os-value")

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=user_env,
    )
    assert p.get_key("usai") == "os-value"


def test_dotenv_resolution_order_is_exact(tmp_path, monkeypatch):
    project_env = tmp_path / "project.env"
    user_env = tmp_path / "user.env"
    _write_env(project_env, USAI_API_KEY="PROJECT")
    _write_env(user_env, USAI_API_KEY="USER")
    monkeypatch.setenv("USAI_API_KEY", "OSENV")

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=user_env,
    )
    assert p.get_key("usai") == "PROJECT"

    project_env.unlink()
    assert p.get_key("usai") == "USER"

    user_env.unlink()
    assert p.get_key("usai") == "OSENV"


def test_dotenv_missing_raises(tmp_path):
    project_env = tmp_path / "missing.env"
    user_env = tmp_path / "missing_user.env"

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=user_env,
    )
    with pytest.raises(CredentialNotFoundError) as excinfo:
        p.get_key("usai")
    msg = str(excinfo.value)
    assert str(project_env) in msg
    assert str(user_env) in msg
    assert "USAI_API_KEY" in msg


def test_dotenv_unknown_provider_raises(tmp_path):
    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=tmp_path / "x.env",
        user_env=tmp_path / "y.env",
    )
    with pytest.raises(CredentialNotFoundError, match="openrouter"):
        p.get_key("openrouter")


def test_dotenv_empty_value_treated_as_missing(tmp_path, monkeypatch):
    project_env = tmp_path / "project.env"
    user_env = tmp_path / "user.env"
    _write_env(project_env, USAI_API_KEY="")
    _write_env(user_env, USAI_API_KEY="from-user")
    monkeypatch.setenv("USAI_API_KEY", "")

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=user_env,
    )
    assert p.get_key("usai") == "from-user"


def test_dotenv_whitespace_stripped(tmp_path):
    project_env = tmp_path / "project.env"
    project_env.write_text("USAI_API_KEY=  abc123  \n")
    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=tmp_path / "u.env",
    )
    assert p.get_key("usai") == "abc123"


def test_dotenv_does_not_mutate_os_environ(tmp_path, monkeypatch):
    project_env = tmp_path / "project.env"
    _write_env(project_env, USAI_API_KEY="secret")

    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY"},
        project_env=project_env,
        user_env=tmp_path / "u.env",
    )
    assert "USAI_API_KEY" not in __import__("os").environ
    p.get_key("usai")
    import os as _os
    assert "USAI_API_KEY" not in _os.environ


def test_dotenv_multi_provider(tmp_path):
    project_env = tmp_path / "project.env"
    _write_env(
        project_env,
        USAI_API_KEY="usai-val",
        OPENROUTER_API_KEY="or-val",
    )
    p = DotEnvProvider(
        providers={"usai": "USAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"},
        project_env=project_env,
        user_env=tmp_path / "u.env",
    )
    assert p.get_key("usai") == "usai-val"
    assert p.get_key("openrouter") == "or-val"


# ---------- EnvVarProvider (3) --------------------------------------------


def test_envvar_returns_value(monkeypatch):
    monkeypatch.setenv("USAI_API_KEY", "env-value")
    p = EnvVarProvider(providers={"usai": "USAI_API_KEY"})
    assert p.get_key("usai") == "env-value"


def test_envvar_missing_raises():
    p = EnvVarProvider(providers={"usai": "USAI_API_KEY"})
    with pytest.raises(CredentialNotFoundError, match="USAI_API_KEY"):
        p.get_key("usai")


def test_envvar_unknown_provider_raises():
    p = EnvVarProvider(providers={"usai": "USAI_API_KEY"})
    with pytest.raises(CredentialNotFoundError, match="openrouter"):
        p.get_key("openrouter")


# ---------- AzureKeyVaultProvider (3, gated) ------------------------------


def test_azure_import_error_if_sdk_missing(monkeypatch):
    """If azure.identity cannot import, constructor raises CredentialBackendError."""
    # Hide azure.* from the import machinery for this test.
    for name in list(sys.modules):
        if name.startswith("azure"):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "azure.identity", None)

    with pytest.raises(CredentialBackendError, match="azure"):
        AzureKeyVaultProvider(
            providers={"usai": "usai-secret"},
            vault_url="https://fake.vault.azure.net",
        )


def test_azure_retrieves_secret(monkeypatch):
    pytest.importorskip("azure.identity")
    pytest.importorskip("azure.keyvault.secrets")

    from azure.keyvault import secrets as kv_secrets

    class _StubSecret:
        def __init__(self, value):
            self.value = value

    class _StubSecretClient:
        def __init__(self, vault_url, credential):
            self.vault_url = vault_url

        def get_secret(self, name):
            return _StubSecret(f"value-for-{name}")

    monkeypatch.setattr(kv_secrets, "SecretClient", _StubSecretClient)

    p = AzureKeyVaultProvider(
        providers={"usai": "usai-secret"},
        vault_url="https://fake.vault.azure.net",
    )
    assert p.get_key("usai") == "value-for-usai-secret"


def test_azure_unknown_provider_raises(monkeypatch):
    pytest.importorskip("azure.identity")
    pytest.importorskip("azure.keyvault.secrets")

    from azure.keyvault import secrets as kv_secrets

    class _StubSecretClient:
        def __init__(self, vault_url, credential):
            pass

        def get_secret(self, name):
            raise AssertionError("should not be called")

    monkeypatch.setattr(kv_secrets, "SecretClient", _StubSecretClient)

    p = AzureKeyVaultProvider(
        providers={"usai": "usai-secret"},
        vault_url="https://fake.vault.azure.net",
    )
    with pytest.raises(CredentialNotFoundError, match="openrouter"):
        p.get_key("openrouter")


# ---------- user_config_env_path (4) --------------------------------------


def test_user_config_path_linux_default(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p = user_config_env_path()
    assert p == Path.home() / ".config" / "usai-harness" / ".env"


def test_user_config_path_xdg_override(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    p = user_config_env_path()
    assert p == tmp_path / "usai-harness" / ".env"


def test_user_config_path_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p = user_config_env_path()
    # Mac uses XDG-style path per ADR-008, not Library/Application Support.
    assert p == Path.home() / ".config" / "usai-harness" / ".env"


def test_user_config_path_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = user_config_env_path()
    assert p == tmp_path / "usai-harness" / ".env"


# ---------- Factory (3) ---------------------------------------------------


def test_factory_dotenv():
    p = make_credential_provider("dotenv", providers={"usai": "USAI_API_KEY"})
    assert isinstance(p, DotEnvProvider)


def test_factory_env_var():
    p = make_credential_provider("env_var", providers={"usai": "USAI_API_KEY"})
    assert isinstance(p, EnvVarProvider)


def test_factory_unknown_raises():
    with pytest.raises(ValueError, match="Unknown credential backend"):
        make_credential_provider("magic", providers={})
