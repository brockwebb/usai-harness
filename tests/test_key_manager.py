"""Tests for the minimal KeyManager loader (ADR-002, reactive auth).

Every test creates its own .env inside pytest's tmp_path. The autouse fixture
strips USAI_* vars from os.environ so load_dotenv inside KeyManager always
reads from the tmp .env, never from the developer's shell.
"""

from pathlib import Path

import pytest

from usai_harness.key_manager import KeyManager


def _write_env(tmp_path: Path, *, api_key: str | None = None,
               base_url: str | None = None) -> Path:
    env_path = tmp_path / ".env"
    lines = []
    if api_key is not None:
        lines.append(f"USAI_API_KEY={api_key}")
    if base_url is not None:
        lines.append(f"USAI_BASE_URL={base_url}")
    env_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return env_path


@pytest.fixture(autouse=True)
def _isolate_usai_env(monkeypatch):
    """Strip USAi env vars so load_dotenv inside KeyManager reads the tmp .env."""
    monkeypatch.delenv("USAI_API_KEY", raising=False)
    monkeypatch.delenv("USAI_BASE_URL", raising=False)


def test_valid_env_loads(tmp_path):
    env_path = _write_env(
        tmp_path,
        api_key="test-key-AAAAAAAA",
        base_url="https://example.com/v1",
    )

    km = KeyManager(env_path=env_path)

    assert km.api_key == "test-key-AAAAAAAA"
    assert km.base_url == "https://example.com/v1"


def test_missing_api_key_raises(tmp_path):
    env_path = _write_env(tmp_path, base_url="https://example.com/v1")

    with pytest.raises(ValueError, match="USAI_API_KEY"):
        KeyManager(env_path=env_path)


def test_missing_base_url_raises(tmp_path):
    env_path = _write_env(tmp_path, api_key="test-key-AAAAAAAA")

    with pytest.raises(ValueError, match="USAI_BASE_URL"):
        KeyManager(env_path=env_path)


def test_empty_env_raises(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("")

    with pytest.raises(ValueError):
        KeyManager(env_path=env_path)


def test_whitespace_only_values_raise(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("USAI_API_KEY=   \nUSAI_BASE_URL=   \n")

    with pytest.raises(ValueError):
        KeyManager(env_path=env_path)


def test_explicit_env_path(tmp_path):
    nested = tmp_path / "nested" / "config"
    nested.mkdir(parents=True)
    env_path = nested / ".env"
    env_path.write_text(
        "USAI_API_KEY=explicit-path-key\n"
        "USAI_BASE_URL=https://explicit.example.com/v1\n"
    )

    km = KeyManager(env_path=env_path)

    assert km.api_key == "explicit-path-key"
    assert km.base_url == "https://explicit.example.com/v1"


def test_no_meta_file_created(tmp_path, monkeypatch):
    """Structural regression guard: the removed meta file must not come back."""
    env_path = _write_env(
        tmp_path,
        api_key="test-key-AAAAAAAA",
        base_url="https://example.com/v1",
    )
    monkeypatch.chdir(tmp_path)

    KeyManager(env_path=env_path)

    leftover = list(tmp_path.rglob(".usai_key_meta.json"))
    assert leftover == [], f"unexpected meta files: {leftover}"
