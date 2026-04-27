"""Tests for the argparse dispatcher in usai_harness.cli."""

import pytest

from usai_harness import cli as cli_mod


@pytest.fixture
def recorder():
    calls: list[tuple[str, tuple, dict]] = []

    def make(name, return_code=0):
        def _fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            return return_code
        return _fn

    return calls, make


def test_report_invokes_generate_and_format(monkeypatch, capsys):
    calls = []

    def fake_generate(path):
        calls.append(("generate", path))
        return {"k": "v"}

    def fake_format(report):
        calls.append(("format", report))
        return "REPORT_OUT"

    monkeypatch.setattr(cli_mod, "generate_report", fake_generate)
    monkeypatch.setattr(cli_mod, "format_report", fake_format)
    rc = cli_mod.cli_main(["report", "run.jsonl"])
    out = capsys.readouterr().out

    assert rc == 0
    assert ("generate", "run.jsonl") in calls
    assert ("format", {"k": "v"}) in calls
    assert "REPORT_OUT" in out


def test_cost_report_passes_flags(monkeypatch, capsys):
    received = {}

    def fake_cost_report(ledger, project=None, model=None):
        received["ledger"] = ledger
        received["project"] = project
        received["model"] = model
        return "COST_OUT"

    monkeypatch.setattr(cli_mod, "cost_report", fake_cost_report)
    rc = cli_mod.cli_main([
        "cost-report", "--ledger", "my.jsonl",
        "--project", "p1", "--model", "m1",
    ])
    out = capsys.readouterr().out

    assert rc == 0
    assert received == {"ledger": "my.jsonl", "project": "p1", "model": "m1"}
    assert "COST_OUT" in out


def test_init_invokes_handler(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_init", make("init"))
    rc = cli_mod.cli_main(["init"])
    assert rc == 0
    assert calls == [("init", (), {})]


def test_add_provider_passes_name(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_add_provider", make("add"))
    rc = cli_mod.cli_main(["add-provider", "openrouter"])
    assert rc == 0
    assert calls == [("add", ("openrouter",), {})]


def test_discover_models_no_arg(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_discover_models", make("dm"))
    rc = cli_mod.cli_main(["discover-models"])
    assert rc == 0
    assert calls == [("dm", (None,), {})]


def test_discover_models_with_provider(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_discover_models", make("dm"))
    rc = cli_mod.cli_main(["discover-models", "usai"])
    assert rc == 0
    assert calls == [("dm", ("usai",), {})]


def test_verify_invokes_handler(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_verify", make("verify"))
    rc = cli_mod.cli_main(["verify"])
    assert rc == 0
    assert calls == [("verify", (), {})]


def test_ping_invokes_handler(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_ping", make("ping"))
    rc = cli_mod.cli_main(["ping"])
    assert rc == 0
    assert calls == [("ping", (), {"model": None})]


def test_ping_passes_model_flag(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_ping", make("ping"))
    rc = cli_mod.cli_main(["ping", "--model", "models/gemini-2.5-flash"])
    assert rc == 0
    assert calls == [("ping", (), {"model": "models/gemini-2.5-flash"})]


def test_audit_default(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_audit", make("audit"))
    rc = cli_mod.cli_main(["audit"])
    assert rc == 0
    assert calls == [("audit", (), {"fix_gitignore": False})]


def test_audit_fix_gitignore(monkeypatch, recorder):
    calls, make = recorder
    monkeypatch.setattr(cli_mod, "handle_audit", make("audit"))
    rc = cli_mod.cli_main(["audit", "--fix-gitignore"])
    assert rc == 0
    assert calls == [("audit", (), {"fix_gitignore": True})]


def test_no_subcommand_fails():
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.cli_main([])
    assert excinfo.value.code != 0
