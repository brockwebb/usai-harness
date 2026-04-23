"""Tests for post-run reporting and CLI."""

import json
import sys

import pytest

from usai_harness.report import (
    cli_main,
    cost_report,
    format_report,
    generate_report,
)


def _entry(**overrides):
    base = {
        "timestamp": "2026-04-22T12:00:00+00:00",
        "job_id": "J1",
        "project": "testproj",
        "task_id": "t1",
        "model": "llama-4-maverick",
        "status_code": 200,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "latency_ms": 500.0,
    }
    base.update(overrides)
    return base


def _write_log(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _ledger_entry(**overrides):
    base = {
        "timestamp": "2026-04-22T12:00:00+00:00",
        "job_id": "J1",
        "job_name": "run",
        "project": "p",
        "model": "llama-4-maverick",
        "total_calls": 10,
        "successful_calls": 10,
        "failed_calls": 0,
        "success_rate": 1.0,
        "total_tokens_in": 1000,
        "total_tokens_out": 500,
        "estimated_cost": 0.0,
        "duration_seconds": 10.0,
    }
    base.update(overrides)
    return base


def _write_ledger(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_generate_report_basic(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_log(path, [
        _entry(task_id=f"t{i}", prompt_tokens=100, completion_tokens=50,
               latency_ms=500.0) for i in range(10)
    ])

    rep = generate_report(path)
    assert rep["total_calls"] == 10
    assert rep["successful_calls"] == 10
    assert rep["failed_calls"] == 0
    assert rep["success_rate"] == 1.0
    assert rep["total_input_tokens"] == 1000
    assert rep["total_output_tokens"] == 500
    assert rep["total_tokens"] == 1500


def test_latency_statistics(tmp_path):
    path = tmp_path / "run.jsonl"
    latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    _write_log(path, [
        _entry(task_id=f"t{i}", latency_ms=lat) for i, lat in enumerate(latencies)
    ])

    rep = generate_report(path)
    assert rep["latency_mean_ms"] == pytest.approx(550)
    assert rep["latency_min_ms"] == 100
    assert rep["latency_max_ms"] == 1000
    assert 900 <= rep["latency_p95_ms"] <= 1000


def test_mixed_success_failure(tmp_path):
    path = tmp_path / "run.jsonl"
    entries = [_entry(task_id=f"t{i}") for i in range(8)]
    entries += [_entry(task_id=f"f{i}", status_code=500) for i in range(2)]
    _write_log(path, entries)

    rep = generate_report(path)
    assert rep["successful_calls"] == 8
    assert rep["failed_calls"] == 2
    assert rep["success_rate"] == pytest.approx(0.8)
    assert rep["errors"]["count"] == 2
    assert rep["errors"]["types"].get(500) == 2


def test_insights_low_success_rate(tmp_path):
    path = tmp_path / "run.jsonl"
    entries = [_entry(task_id=f"t{i}") for i in range(9)]
    entries.append(_entry(task_id="f1", status_code=500))
    _write_log(path, entries)

    rep = generate_report(path)
    assert any("95%" in ins for ins in rep["insights"])


def test_insights_429_detected(tmp_path):
    path = tmp_path / "run.jsonl"
    entries = [_entry(task_id=f"t{i}") for i in range(5)]
    entries += [_entry(task_id=f"r{i}", status_code=429) for i in range(2)]
    _write_log(path, entries)

    rep = generate_report(path)
    assert any("rate limit" in ins.lower() for ins in rep["insights"])


def test_insights_perfect_run(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_log(path, [_entry(task_id=f"t{i}") for i in range(20)])

    rep = generate_report(path)
    assert any("perfect" in ins.lower() for ins in rep["insights"])


def test_empty_log_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert generate_report(path) == {}


def test_missing_log_file(tmp_path):
    assert generate_report(tmp_path / "nope.jsonl") == {}


def test_format_report_output(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_log(path, [_entry(task_id=f"t{i}") for i in range(10)])

    out = format_report(generate_report(path))
    for label in ("Job:", "Calls:", "Latency:", "Tokens:"):
        assert label in out


def test_cost_report_basic(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        _ledger_entry(job_id=f"J{i}", estimated_cost=0.50) for i in range(3)
    ])

    out = cost_report(str(ledger))
    # Total = 1.50
    assert "1.50" in out


def test_cost_report_project_filter(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        _ledger_entry(job_id="J1", project="alpha", estimated_cost=1.00,
                      total_calls=10),
        _ledger_entry(job_id="J2", project="beta", estimated_cost=2.00,
                      total_calls=20,
                      timestamp="2026-04-22T13:00:00+00:00"),
    ])

    out = cost_report(str(ledger), project="alpha")
    assert "alpha" in out
    assert "beta" not in out


def test_cost_report_empty_ledger(tmp_path):
    out = cost_report(str(tmp_path / "nope.jsonl"))
    assert "no" in out.lower() and ("data" in out.lower() or "entries" in out.lower())


def test_cli_report_command(tmp_path, monkeypatch, capsys):
    path = tmp_path / "run.jsonl"
    _write_log(path, [_entry(task_id=f"t{i}") for i in range(5)])

    monkeypatch.setattr(sys, "argv", ["usai-harness", "report", str(path)])
    cli_main()
    out = capsys.readouterr().out
    assert "Job:" in out or "Calls:" in out


def test_cli_cost_report_command(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [_ledger_entry()])

    monkeypatch.setattr(sys, "argv",
                        ["usai-harness", "cost-report", "--ledger", str(ledger)])
    cli_main()
    assert capsys.readouterr().out.strip()


def test_cli_no_command(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["usai-harness"])
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 1
