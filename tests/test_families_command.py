"""Tests for `usai-harness families` (ADR-014)."""

import yaml

from usai_harness.setup_commands import handle_families


def test_families_command_lists_all_families(capsys):
    rc = handle_families()
    assert rc == 0
    out = capsys.readouterr().out
    for key in (
        "claude-sonnet-4", "claude-opus-4", "claude-haiku-4",
        "gemini-2.5", "gemini-2.0", "gpt-5", "o-reasoning",
        "llama-4", "grok-4",
    ):
        assert key in out


def test_families_command_shows_one_family(capsys):
    rc = handle_families(family="claude-sonnet-4")
    assert rc == 0
    out = capsys.readouterr().out
    assert "claude-sonnet-4" in out
    assert "anthropic" in out
    # Detail view shows parameter rows.
    assert "temperature" in out
    assert "False" in out


def test_families_command_yaml_format(capsys):
    rc = handle_families(output_format="yaml")
    assert rc == 0
    out = capsys.readouterr().out
    parsed = yaml.safe_load(out)
    assert "families" in parsed
    assert "claude-sonnet-4" in parsed["families"]
    assert "provider_aliases" in parsed


def test_families_command_unknown_family_returns_1(capsys):
    rc = handle_families(family="not-a-real-family")
    assert rc == 1
    err = capsys.readouterr().err
    assert "not-a-real-family" in err
    assert "claude-sonnet-4" in err  # lists available families


def test_families_command_markdown_format(capsys):
    rc = handle_families(output_format="markdown")
    assert rc == 0
    out = capsys.readouterr().out
    assert "###" in out
    assert "| Parameter |" in out
