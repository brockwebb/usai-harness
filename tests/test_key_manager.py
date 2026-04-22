"""Tests for key lifecycle, expiry, rotation detection.

Every test creates its own .env and meta file inside pytest's tmp_path so the
real project .env and real shell environment are never touched. The autouse
fixture strips USAI_* vars from os.environ so load_dotenv inside KeyManager
always reads from the tmp .env, never from the developer's shell.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from usai_harness.key_manager import KeyExpiredError, KeyManager


def _hash_last_8(key: str) -> str:
    return hashlib.sha256(key[-8:].encode()).hexdigest()


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


def _write_meta(meta_path: Path, *, key_hash: str, issued_at: datetime,
                rotations: list | None = None) -> None:
    meta_path.write_text(json.dumps({
        "key_hash": key_hash,
        "issued_at": issued_at.isoformat(),
        "rotations": rotations or [],
    }))


@pytest.fixture(autouse=True)
def _isolate_usai_env(monkeypatch):
    """Strip USAi env vars so load_dotenv inside KeyManager reads the tmp .env."""
    monkeypatch.delenv("USAI_API_KEY", raising=False)
    monkeypatch.delenv("USAI_BASE_URL", raising=False)


def test_valid_key_loads(tmp_path):
    env_path = _write_env(tmp_path, api_key="test-key-AAAAAAAA",
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"

    km = KeyManager(env_path=env_path, meta_path=meta_path)

    assert km.is_valid is True
    assert km.api_key == "test-key-AAAAAAAA"
    assert km.base_url == "https://example.com/v1"
    assert meta_path.exists()


def test_missing_api_key_raises(tmp_path):
    env_path = _write_env(tmp_path, base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"

    with pytest.raises(ValueError, match="USAI_API_KEY"):
        KeyManager(env_path=env_path, meta_path=meta_path)


def test_missing_base_url_raises(tmp_path):
    env_path = _write_env(tmp_path, api_key="test-key-AAAAAAAA")
    meta_path = tmp_path / ".usai_key_meta.json"

    with pytest.raises(ValueError, match="USAI_BASE_URL"):
        KeyManager(env_path=env_path, meta_path=meta_path)


def test_empty_env_file_raises(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("")
    meta_path = tmp_path / ".usai_key_meta.json"

    with pytest.raises(ValueError):
        KeyManager(env_path=env_path, meta_path=meta_path)


def test_expired_key_raises(tmp_path):
    api_key = "test-key-AAAAAAAA"
    env_path = _write_env(tmp_path, api_key=api_key,
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"
    issued = datetime.now(timezone.utc) - timedelta(days=8)
    _write_meta(meta_path, key_hash=_hash_last_8(api_key), issued_at=issued)

    with pytest.raises(KeyExpiredError):
        KeyManager(env_path=env_path, meta_path=meta_path)


def test_expiring_soon_warns(tmp_path, caplog):
    api_key = "test-key-AAAAAAAA"
    env_path = _write_env(tmp_path, api_key=api_key,
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"
    issued = datetime.now(timezone.utc) - timedelta(days=6, hours=2)
    _write_meta(meta_path, key_hash=_hash_last_8(api_key), issued_at=issued)

    caplog.set_level(logging.WARNING, logger="usai_harness.key_manager")
    km = KeyManager(env_path=env_path, meta_path=meta_path)

    assert km.is_valid is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING when key expires within 24h"
    assert any("expire" in r.getMessage().lower() for r in warnings)


def test_key_rotation_detected(tmp_path, caplog):
    current_key = "test-key-AAAAAAAA"
    old_key = "test-key-BBBBBBBB"
    env_path = _write_env(tmp_path, api_key=current_key,
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"
    old_issued = datetime.now(timezone.utc) - timedelta(days=3)
    _write_meta(meta_path, key_hash=_hash_last_8(old_key), issued_at=old_issued)

    caplog.set_level(logging.INFO, logger="usai_harness.key_manager")
    KeyManager(env_path=env_path, meta_path=meta_path)

    meta = json.loads(meta_path.read_text())
    assert meta["key_hash"] == _hash_last_8(current_key)
    assert any("rotat" in r.getMessage().lower() for r in caplog.records)


def test_set_issued_at_override(tmp_path):
    api_key = "test-key-AAAAAAAA"
    env_path = _write_env(tmp_path, api_key=api_key,
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"

    km = KeyManager(env_path=env_path, meta_path=meta_path)
    explicit = datetime.now(timezone.utc) - timedelta(hours=10)
    km.set_issued_at(explicit)

    assert km.issued_at == explicit
    assert km.expires_at == explicit + timedelta(days=7)
    meta = json.loads(meta_path.read_text())
    assert meta["issued_at"] == explicit.isoformat()


def test_default_issued_at_offset(tmp_path):
    api_key = "test-key-AAAAAAAA"
    env_path = _write_env(tmp_path, api_key=api_key,
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"

    before = datetime.now(timezone.utc)
    km = KeyManager(env_path=env_path, meta_path=meta_path)
    after = datetime.now(timezone.utc)

    earliest = before - timedelta(hours=4, seconds=5)
    latest = after - timedelta(hours=4) + timedelta(seconds=5)
    assert earliest <= km.issued_at <= latest


def test_meta_file_persists_across_instances(tmp_path):
    api_key = "test-key-AAAAAAAA"
    env_path = _write_env(tmp_path, api_key=api_key,
                          base_url="https://example.com/v1")
    meta_path = tmp_path / ".usai_key_meta.json"

    km1 = KeyManager(env_path=env_path, meta_path=meta_path)
    first_issued = km1.issued_at

    km2 = KeyManager(env_path=env_path, meta_path=meta_path)
    assert km2.issued_at == first_issued
