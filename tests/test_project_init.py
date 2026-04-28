"""Tests for `usai-harness project-init` (ADR-013, FR-053..058, IR-006)."""

import ast
import json
from pathlib import Path

import pytest

from usai_harness import setup_commands
from usai_harness.transport import BaseTransport


class _MockTransport(BaseTransport):
    """Programmable transport for project-init smoke-test injection."""

    def __init__(self, *, status_code: int = 200, content: str = "OK"):
        self.status_code = status_code
        self.content = content
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages, **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        body = {
            "choices": [{"message": {"role": "assistant", "content": self.content}}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 1, "total_tokens": 7},
            "model": model,
        }
        if 200 <= self.status_code < 300:
            return body, self.status_code
        return {"error_body": "simulated failure"}, self.status_code

    async def close(self):
        self.closed = True


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """Run handle_project_init from a fresh tmp directory with a credential available."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USAI_API_KEY", "test-key-AAAAAAAA")
    return tmp_path


def test_project_init_creates_config(project_root):
    rc = setup_commands.handle_project_init(transport=_MockTransport())
    assert rc == 0
    cfg = project_root / "usai_harness.yaml"
    assert cfg.exists()
    text = cfg.read_text()
    assert "project:" in text
    assert "models:" in text
    assert "default_model:" in text
    assert "{project_name}" not in text
    assert "{provider_name}" not in text
    assert "{default_model_name}" not in text


def test_project_init_creates_directories(project_root):
    setup_commands.handle_project_init(transport=_MockTransport())
    for sub in ("output", "output/logs", "tevv", "scripts"):
        assert (project_root / sub).is_dir(), f"missing {sub}"


def test_project_init_creates_example_script(project_root):
    setup_commands.handle_project_init(transport=_MockTransport())
    script = project_root / "scripts" / "example_batch.py"
    assert script.exists()
    # Must parse as valid Python.
    ast.parse(script.read_text(encoding="utf-8"))


def test_project_init_appends_gitignore(project_root):
    (project_root / ".gitignore").write_text(
        "# pre-existing\n*.pyc\n", encoding="utf-8",
    )
    setup_commands.handle_project_init(transport=_MockTransport())
    text = (project_root / ".gitignore").read_text()
    assert "*.pyc" in text
    assert "output/cost_ledger.jsonl" in text
    assert "output/logs/" in text


def test_project_init_does_not_overwrite_config(project_root):
    cfg = project_root / "usai_harness.yaml"
    sentinel = "# user-edited config; do not overwrite\nproject: keep-me\n"
    cfg.write_text(sentinel, encoding="utf-8")
    setup_commands.handle_project_init(transport=_MockTransport())
    assert cfg.read_text() == sentinel


def test_project_init_idempotent(project_root):
    """Second run produces a fresh TEVV report; gitignore is not duplicated."""
    setup_commands.handle_project_init(transport=_MockTransport())
    first_reports = sorted((project_root / "tevv").glob("init_report_*.md"))
    gi_first = (project_root / ".gitignore").read_text()

    # Tiny gap so the second timestamp differs (to-the-second precision).
    import time
    time.sleep(1.05)

    setup_commands.handle_project_init(transport=_MockTransport())
    second_reports = sorted((project_root / "tevv").glob("init_report_*.md"))
    gi_second = (project_root / ".gitignore").read_text()

    assert len(second_reports) == len(first_reports) + 1
    # Gitignore lines not duplicated.
    assert gi_first.count("output/cost_ledger.jsonl") == 1
    assert gi_second.count("output/cost_ledger.jsonl") == 1


def test_project_init_tevv_pass(project_root):
    rc = setup_commands.handle_project_init(transport=_MockTransport(content="OK"))
    assert rc == 0
    reports = sorted((project_root / "tevv").glob("init_report_*.md"))
    assert reports, "no TEVV report written"
    text = reports[-1].read_text()
    assert "**Verdict:** PASS" in text
    assert "## Verdict" in text
    assert "PASS" in text


def test_project_init_tevv_fail_status(project_root):
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(status_code=500, content="ignored"),
    )
    assert rc == 1
    text = sorted((project_root / "tevv").glob("init_report_*.md"))[-1].read_text()
    assert "**Verdict:** FAIL" in text
    assert "## Failure" in text
    assert "500" in text


def test_project_init_tevv_fail_content(project_root):
    rc = setup_commands.handle_project_init(
        transport=_MockTransport(status_code=200, content="something else entirely"),
    )
    assert rc == 1
    text = sorted((project_root / "tevv").glob("init_report_*.md"))[-1].read_text()
    assert "**Verdict:** FAIL" in text
    assert "did not contain" in text
    assert "something else entirely" in text
