"""Key Manager: minimal credential loader.

Per ADR-002, expiry is the endpoint's responsibility; a 401/403 halts
the worker pool (see worker_pool.AuthHaltError). This module only reads
USAI_API_KEY and USAI_BASE_URL from .env (or the environment) and fails
loudly at startup if either is missing.
"""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


class KeyManager:
    """Loads USAi credentials from .env. No expiry management; endpoint is truth (ADR-002)."""

    def __init__(self, env_path=None):
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

        self.api_key: str = api_key
        self.base_url: str = base_url

    @staticmethod
    def _resolve_env_path(env_path) -> Path | None:
        if env_path is not None:
            return Path(env_path)
        found = find_dotenv(usecwd=True)
        return Path(found) if found else None
