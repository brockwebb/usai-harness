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
