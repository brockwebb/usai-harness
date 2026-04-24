"""Tests for post-run reporting logic. CLI dispatcher is tested in test_cli.py."""

import json

import pytest

from usai_harness.report import (
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
        "model": "claude-sonnet-4-5-20241022",
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
        "model": "claude-sonnet-4-5-20241022",
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


# ---------- model echo (FR-029) -------------------------------------------


def test_report_detects_mismatch(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_log(path, [
        _entry(task_id="t0", model_requested="claude-sonnet-4-5-20241022",
               model_returned="claude-sonnet-4-5-20241022"),
        _entry(task_id="t1", model_requested="claude-sonnet-4-5-20241022",
               model_returned="claude-opus-4-5"),
        _entry(task_id="t2", model_requested="claude-sonnet-4-5-20241022",
               model_returned="gemini-2-5-pro"),
    ])
    rpt = generate_report(path)
    assert len(rpt["model_mismatches"]) == 2
    ids = {m["task_id"] for m in rpt["model_mismatches"]}
    assert ids == {"t1", "t2"}

    text = format_report(rpt)
    assert "Model echo:" in text
    assert "2 mismatch" in text


def test_report_no_section_when_no_mismatches(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_log(path, [
        _entry(task_id="t0", model_requested="claude-sonnet-4-5-20241022",
               model_returned="claude-sonnet-4-5-20241022"),
    ])
    rpt = generate_report(path)
    assert rpt["model_mismatches"] == []
    assert "Model echo" not in format_report(rpt)


def test_report_old_log_format_still_works(tmp_path):
    """Backward-compat: a log with only 'model' (no 'model_requested') still reports."""
    path = tmp_path / "legacy.jsonl"
    _write_log(path, [
        # _entry() already uses 'model', not 'model_requested', so this is the old shape.
        _entry(task_id=f"t{i}") for i in range(3)
    ])
    rpt = generate_report(path)
    assert rpt["total_calls"] == 3
    # No mismatches because model_returned is absent in old logs.
    assert rpt["model_mismatches"] == []
    assert rpt["model"] == "claude-sonnet-4-5-20241022"


