"""Tests for usai_harness.audit_command."""

import subprocess

import pytest

from usai_harness import audit_command
from usai_harness.audit_command import REQUIRED_GITIGNORE_PATTERNS, handle_audit


def _init_git_repo(repo: str) -> None:
    subprocess.run(
        ["git", "init", "-q"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=repo, check=True, capture_output=True,
    )


def _stage(repo_root) -> None:
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(repo_root), check=True, capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    _init_git_repo(str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _stub_pip_audit(monkeypatch):
    """Default: pip-audit not installed so tests don't depend on host tooling."""
    monkeypatch.setattr(
        audit_command, "_run_pip_audit",
        lambda: (0, "pip-audit not installed (stubbed)"),
    )


def test_gitignore_all_present_passes(repo, capsys):
    gi = repo / ".gitignore"
    gi.write_text("\n".join(REQUIRED_GITIGNORE_PATTERNS) + "\n")
    (repo / "harmless.txt").write_text("hi\n")
    _stage(repo)

    rc = handle_audit(repo_root=repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[gitignore] ok" in out


def test_gitignore_missing_reports(repo, capsys):
    gi = repo / ".gitignore"
    gi.write_text(".env\n")  # only one of the required
    _stage(repo)

    rc = handle_audit(repo_root=repo)
    out = capsys.readouterr().out
    assert rc != 0
    assert "[gitignore] FAIL" in out
    assert "cost_ledger.jsonl" in out


def test_gitignore_missing_fix_appends(repo, capsys):
    gi = repo / ".gitignore"
    gi.write_text(".env\n")
    _stage(repo)

    rc = handle_audit(repo_root=repo, fix_gitignore=True)
    text = gi.read_text()
    for pat in REQUIRED_GITIGNORE_PATTERNS:
        assert pat in text
    out = capsys.readouterr().out
    assert "[gitignore] fixed" in out
    assert rc == 0


def test_tracked_file_with_bearer_reported(repo, capsys):
    gi = repo / ".gitignore"
    gi.write_text("\n".join(REQUIRED_GITIGNORE_PATTERNS) + "\n")
    leak = repo / "leak.py"
    leak.write_text(
        "# header\n"
        'TOKEN = "Bearer abcdef1234567890ABCDEF"\n'
    )
    _stage(repo)

    rc = handle_audit(repo_root=repo)
    out = capsys.readouterr().out
    assert rc != 0
    assert "[secrets]  FAIL" in out
    assert "leak.py:2" in out
    # The matched value itself must never be printed.
    assert "abcdef1234567890ABCDEF" not in out


def test_tracked_file_with_api_key_reported(repo, capsys):
    gi = repo / ".gitignore"
    gi.write_text("\n".join(REQUIRED_GITIGNORE_PATTERNS) + "\n")
    leak = repo / "settings.py"
    leak.write_text('USAI_API_KEY=sk-longvalue1234567890\n')
    _stage(repo)

    rc = handle_audit(repo_root=repo)
    out = capsys.readouterr().out
    assert rc != 0
    assert "settings.py:1" in out
    assert "sk-longvalue1234567890" not in out


def test_no_hits_clean(repo, capsys):
    gi = repo / ".gitignore"
    gi.write_text("\n".join(REQUIRED_GITIGNORE_PATTERNS) + "\n")
    (repo / "ok.py").write_text("print('hello')\n")
    _stage(repo)

    rc = handle_audit(repo_root=repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[secrets]  ok" in out


def test_pip_audit_missing_soft_fails(repo, capsys, monkeypatch):
    gi = repo / ".gitignore"
    gi.write_text("\n".join(REQUIRED_GITIGNORE_PATTERNS) + "\n")
    _stage(repo)

    monkeypatch.setattr(
        audit_command, "_run_pip_audit",
        lambda: (0, "pip-audit not installed (pip install pip-audit to enable)"),
    )
    rc = handle_audit(repo_root=repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "pip-audit" in out
