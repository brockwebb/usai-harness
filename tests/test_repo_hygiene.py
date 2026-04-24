"""Repo-level invariants. Not unit tests; structural checks."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_lock_exists():
    """SEC-006: hash-pinned dependencies must be available."""
    lock = REPO_ROOT / "requirements.lock"
    assert lock.exists(), (
        f"{lock} is missing. Regenerate with "
        "pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml"
    )


def test_requirements_lock_has_hashes():
    """SEC-006: every entry in the lock file must have a --hash= clause."""
    lock = REPO_ROOT / "requirements.lock"
    content = lock.read_text()
    assert "--hash=" in content, (
        "requirements.lock does not contain hash pins. Regenerate with: "
        "pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml"
    )
