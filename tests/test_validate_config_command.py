"""Tests for `usai-harness validate-config` (ADR-015)."""

import sys
import textwrap
from pathlib import Path

import pytest

from usai_harness.setup_commands import handle_validate_config


def _write(tmp_path: Path, body: str, name: str = "project.yaml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_validate_known_good_config_returns_0(tmp_path, capsys):
    cfg = _write(tmp_path, """
        models:
          - name: gemini-2.5-flash
        default_model: gemini-2.5-flash
        workers: 3
    """)
    rc = handle_validate_config(str(cfg))
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "project_config_v1" in out


def test_validate_unknown_field_returns_1(tmp_path, capsys):
    cfg = _write(tmp_path, """
        model: gemini-2.5-flash
        ledger_path: output/cost_ledger.jsonl
    """)
    rc = handle_validate_config(str(cfg))
    assert rc == 1
    err = capsys.readouterr().err
    assert "ledger_path" in err or "additionalProperties" in err.lower()


def test_validate_missing_path_returns_1(tmp_path, capsys):
    rc = handle_validate_config(str(tmp_path / "does-not-exist.yaml"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not exist" in err.lower()


def test_validate_yaml_parse_error_returns_1(tmp_path, capsys):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("models:\n  - name: x\n - bad indent\n")
    rc = handle_validate_config(str(cfg))
    assert rc == 1
    err = capsys.readouterr().err
    assert "yaml" in err.lower() or "parse" in err.lower()


def test_validate_non_mapping_top_level_returns_1(tmp_path, capsys):
    cfg = tmp_path / "list.yaml"
    cfg.write_text("- this is a list, not a mapping\n")
    rc = handle_validate_config(str(cfg))
    assert rc == 1
    err = capsys.readouterr().err
    assert "mapping" in err.lower()


def test_validate_missing_jsonschema_extra_returns_1(tmp_path, monkeypatch, capsys):
    """When jsonschema is not installed, the handler exits 1 with a
    pip-install hint. Simulated by hiding jsonschema from import."""
    cfg = _write(tmp_path, """
        model: gemini-2.5-flash
    """)
    real_modules = dict(sys.modules)
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    try:
        rc = handle_validate_config(str(cfg))
    finally:
        sys.modules.clear()
        sys.modules.update(real_modules)
    assert rc == 1
    err = capsys.readouterr().err
    assert "jsonschema" in err
    assert "validation" in err
