"""Key Manager: Handles API key lifecycle and expiry enforcement.

Responsibilities:
    - Read USAI_API_KEY and USAI_BASE_URL from .env via python-dotenv
    - Track key issued_at in .usai_key_meta.json
    - On new key detection: set issued_at = now() - 4 hours (default buffer)
    - Allow explicit issued_at override
    - Expiry = issued_at + 7 days
    - On init: refuse if expired, warn if < 24 hours remaining, proceed if valid
    - Log all key rotation events

Inputs:
    - env_path: str — path to .env file
    - meta_path: str — path to .usai_key_meta.json

Outputs:
    - base_url: str
    - api_key: str
    - expires_at: datetime
    - is_valid: bool

Errors:
    - KeyExpiredError: raised if key is past expiry. Includes instructions for renewal.
    - KeyExpiringWarning: logged (not raised) if < 24 hours remain.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

log = logging.getLogger(__name__)

KEY_LIFETIME = timedelta(days=7)
DEFAULT_ISSUED_OFFSET = timedelta(hours=4)
EXPIRY_WARNING_THRESHOLD = timedelta(hours=24)
META_FILENAME = ".usai_key_meta.json"


class KeyExpiredError(Exception):
    """Raised when the API key has passed its 7-day expiry window."""
    pass


class KeyManager:
    """Manages USAi API key lifecycle and expiry enforcement."""

    def __init__(self, env_path=None, meta_path=None):
        resolved_env = self._resolve_env_path(env_path)
        if resolved_env is not None:
            load_dotenv(resolved_env)
        else:
            load_dotenv()

        api_key = os.environ.get("USAI_API_KEY", "").strip()
        base_url = os.environ.get("USAI_BASE_URL", "").strip()

        if not api_key:
            raise ValueError(
                "USAI_API_KEY is missing or empty. "
                "Set it in .env (see .env.example for format)."
            )
        if not base_url:
            raise ValueError(
                "USAI_BASE_URL is missing or empty. "
                "Set it in .env (see .env.example for format)."
            )

        if meta_path is None:
            base_dir = Path(resolved_env).parent if resolved_env else Path.cwd()
            meta_path = base_dir / META_FILENAME

        self.api_key: str = api_key
        self.base_url: str = base_url
        self.meta_path: Path = Path(meta_path)
        self.issued_at: datetime
        self.expires_at: datetime
        self._rotations: list[dict] = []

        self._load_or_create_meta()
        self._check_expiry()

    @staticmethod
    def _resolve_env_path(env_path) -> Path | None:
        if env_path is not None:
            return Path(env_path)
        found = find_dotenv(usecwd=True)
        return Path(found) if found else None

    @property
    def is_valid(self) -> bool:
        return datetime.now(timezone.utc) < self.expires_at

    @property
    def hours_remaining(self) -> float:
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds() / 3600.0

    def _current_key_hash(self) -> str:
        return hashlib.sha256(self.api_key[-8:].encode()).hexdigest()

    def _load_or_create_meta(self) -> None:
        current_hash = self._current_key_hash()
        now = datetime.now(timezone.utc)

        if self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text())
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Corrupt meta file at {self.meta_path}: {e}. "
                    f"Delete it to force a fresh key registration."
                ) from e

            self._rotations = list(meta.get("rotations", []))
            stored_hash = meta.get("key_hash")

            if stored_hash == current_hash:
                self.issued_at = datetime.fromisoformat(meta["issued_at"])
                self.expires_at = self.issued_at + KEY_LIFETIME
                return

            # Key hash changed -> rotation detected.
            self.issued_at = now - DEFAULT_ISSUED_OFFSET
            self.expires_at = self.issued_at + KEY_LIFETIME
            self._rotations.append({
                "timestamp": now.isoformat(),
                "event": "key_rotation_detected",
            })
            log.info(
                "USAi API key rotation detected; meta hash updated and "
                "issued_at defaulted to now - 4h (expires %s).",
                self.expires_at.isoformat(),
            )
            self._write_meta()
            return

        # No meta file yet -> brand new key.
        self.issued_at = now - DEFAULT_ISSUED_OFFSET
        self.expires_at = self.issued_at + KEY_LIFETIME
        self._rotations = [{
            "timestamp": now.isoformat(),
            "event": "new_key_detected",
        }]
        log.info(
            "USAi API key registered; issued_at defaulted to now - 4h "
            "(expires %s).",
            self.expires_at.isoformat(),
        )
        self._write_meta()

    def _check_expiry(self) -> None:
        now = datetime.now(timezone.utc)
        if now > self.expires_at:
            raise KeyExpiredError(
                f"USAi API key expired at {self.expires_at.isoformat()}. "
                f"Request a new key from the USAi portal and update .env. "
                f"See .env.example for format."
            )

        remaining = self.expires_at - now
        if remaining < EXPIRY_WARNING_THRESHOLD:
            hours = remaining.total_seconds() / 3600.0
            log.warning(
                "USAi API key expires in %.1f hours (at %s). "
                "Request a new key soon.",
                hours,
                self.expires_at.isoformat(),
            )
        else:
            log.debug(
                "USAi API key valid; %.1f hours remaining.",
                remaining.total_seconds() / 3600.0,
            )

    def set_issued_at(self, dt: datetime) -> None:
        """Override auto-detected issued_at (e.g. exact time from USAi portal)."""
        self.issued_at = dt
        self.expires_at = dt + KEY_LIFETIME
        self._write_meta()
        self._check_expiry()

    def _write_meta(self) -> None:
        payload = {
            "key_hash": self._current_key_hash(),
            "issued_at": self.issued_at.isoformat(),
            "rotations": self._rotations,
        }
        self.meta_path.write_text(json.dumps(payload, indent=2))
